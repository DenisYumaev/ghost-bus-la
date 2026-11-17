"""Decode a compacted UTC day into typed tables (pipeline spec, section 3).

Reads the day's compacted parts through their marker, gunzips one snapshot at a time, and
decodes every frame with `ghostbus_decode.frames`. Per feed and day it writes, under
`derived/decoded/<table>/…/dt=<day>/run=<id>/part-<n>.parquet`:

- `vehicle_position` (vehicle feed) or `trip_update` (trip feed), with the snapshot's
  `fetched_at`, `feed_ts` (newest entity timestamp in the snapshot) and `snapshot_sha`;
- `schema_fingerprint`: one row per snapshot, the input to the schema-drift alert;
- `quarantine`: frames that failed validation, with the reason and the exact bytes
  (base64), so nothing is dropped.

Rows go through newline-delimited JSON into DuckDB with explicit column types (JSON keeps
NULL apart from an empty string, which CSV can't). One output part per compacted part keeps
memory to about one decompressed snapshot plus one part's rows. Same run protocol as
compaction: a fresh `run=<id>/`, then `_SUCCESS` listing every part, then older runs
deleted; readers follow the marker.
"""

import base64
import gzip
import json
import shutil
import tempfile
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, TextIO

import duckdb

from ghostbus_decode.compact import STREAM_FEEDS, compaction_marker
from ghostbus_decode.frames import (
    Quarantined,
    decode_trip_update,
    decode_vehicle,
    fingerprint,
    unwrap,
)
from ghostbus_decode.s3 import Bucket, ReadBucket

DECODER_VERSION = 2
_CHUNK = 25  # snapshots per output part: about 750k trip-update rows, 300 MB of NDJSON
SUCCESS = "_SUCCESS"
TABLE = {"vehicle_positions": "vehicle_position", "trip_updates": "trip_update"}

_SNAPSHOT = {"fetched_at": "TIMESTAMPTZ", "feed_ts": "TIMESTAMPTZ", "snapshot_sha": "VARCHAR"}
_TRIP = {
    "trip_id": "VARCHAR", "route_id": "VARCHAR", "direction_id": "INTEGER",
    "start_date": "DATE", "start_time": "VARCHAR", "trip_schedule_relationship": "VARCHAR",
}  # fmt: skip
COLUMNS = {
    "vehicle_position": {
        **_SNAPSHOT, "vehicle_id": "VARCHAR", **_TRIP, "lat": "DOUBLE", "lon": "DOUBLE",
        "bearing": "DOUBLE", "speed": "DOUBLE", "current_stop_sequence": "INTEGER",
        "stop_id": "VARCHAR", "current_status": "VARCHAR", "vehicle_ts": "TIMESTAMPTZ",
    },
    "trip_update": {
        **_SNAPSHOT, **_TRIP, "vehicle_id": "VARCHAR", "entity_ts": "TIMESTAMPTZ",
        "stop_sequence": "INTEGER", "stop_id": "VARCHAR", "arrival_ts": "TIMESTAMPTZ",
        "departure_ts": "TIMESTAMPTZ", "stop_schedule_relationship": "VARCHAR",
    },
    "schema_fingerprint": {
        "fetched_at": "TIMESTAMPTZ", "snapshot_sha": "VARCHAR", "feed": "VARCHAR",
        "fingerprint": "VARCHAR", "n_frames": "INTEGER", "n_quarantined": "INTEGER",
    },
    "quarantine": {
        "fetched_at": "TIMESTAMPTZ", "snapshot_sha": "VARCHAR", "feed": "VARCHAR",
        "reason": "VARCHAR", "raw_b64": "VARCHAR",
    },
}  # fmt: skip


class NotCompacted(Exception):
    """The day has no compaction marker yet."""


def output_prefix(table: str, feed: str, day: date) -> str:
    feed_part = "" if table in TABLE.values() else f"feed={feed}/"
    name = "_quarantine" if table == "quarantine" else table
    return f"derived/decoded/{name}/{feed_part}dt={day.isoformat()}/"


def _marker_key(feed: str, day: date) -> str:
    return output_prefix(TABLE[feed], feed, day) + SUCCESS


def decoded_parts(bucket: ReadBucket, feed: str, day: date) -> dict[str, list[str]]:
    """Part files per output table of the day's last complete run; {} if none."""
    key = _marker_key(feed, day)
    if key not in bucket.list_keys(key.rsplit("/", 1)[0] + "/"):
        return {}
    parts: dict[str, list[str]] = json.loads(bucket.get(key))["part_keys"]
    return parts


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _write(f: TextIO, row: dict[str, Any]) -> None:
    f.write(json.dumps({k: _iso(v) for k, v in row.items()}))
    f.write("\n")


class _Stats:
    def __init__(self) -> None:
        self.snapshots = self.frames = self.rows = self.quarantined = 0
        self.reasons: Counter[str] = Counter()
        self.fingerprints: set[str] = set()


def _decode_snapshot(
    feed: str, fetched_at: str, sha: str, payload: bytes, out: dict[str, TextIO], stats: _Stats
) -> None:
    lines = gzip.decompress(payload).split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()  # the snapshot ends with a newline; that's the only blank to skip
    frames: list[bytes] = []
    rows: list[dict[str, Any]] = []
    bad = 0
    for line in lines:
        unwrapped = unwrap(line)
        raw = line if isinstance(unwrapped, Quarantined) else unwrapped
        frames.append(raw)
        result: Any
        if isinstance(unwrapped, Quarantined):
            result = unwrapped
        elif not raw.strip():
            result = Quarantined("empty", raw)  # ingest stores an empty frame as its own line
        elif feed == "vehicle_positions":
            result = decode_vehicle(raw)
        else:
            result = decode_trip_update(raw)
        if isinstance(result, Quarantined):
            bad += 1
            stats.reasons[result.reason] += 1
            _write(out["quarantine"], {"fetched_at": fetched_at, "snapshot_sha": sha,
                                       "feed": feed, "reason": result.reason,
                                       "raw_b64": base64.b64encode(raw).decode()})  # fmt: skip
        elif isinstance(result, list):
            rows.extend(result)
        else:
            rows.append(result)
    stamps = [r.get("vehicle_ts") or r.get("entity_ts") for r in rows]
    feed_ts = max((s for s in stamps if s is not None), default=None)
    for row in rows:
        _write(out[TABLE[feed]], {"fetched_at": fetched_at, "feed_ts": feed_ts,
                                  "snapshot_sha": sha, **row})  # fmt: skip
    fp = fingerprint(frames)
    stats.fingerprints.add(fp)
    _write(out["schema_fingerprint"], {"fetched_at": fetched_at, "snapshot_sha": sha,
                                       "feed": feed, "fingerprint": fp,
                                       "n_frames": len(frames), "n_quarantined": bad})  # fmt: skip
    stats.snapshots += 1
    stats.frames += len(frames)
    stats.rows += len(rows)
    stats.quarantined += bad


def decode_day(
    bucket: Bucket, feed: str, day: date, workdir: Path | None = None, run_id: str | None = None
) -> dict[str, Any]:
    if feed not in STREAM_FEEDS:
        raise ValueError(f"not a stream feed: {feed!r}")
    source = compaction_marker(bucket, feed, day)
    if source is None:
        raise NotCompacted(f"{feed} {day}: no compaction marker; run `make compact` first")
    parts: list[str] = source["part_keys"]
    tables = [TABLE[feed], "schema_fingerprint", "quarantine"]
    run = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    before = {k for t in tables for k in bucket.list_keys(output_prefix(t, feed, day))}
    stats = _Stats()
    written: dict[str, list[str]] = {t: [] for t in tables}
    tmp = Path(tempfile.mkdtemp(dir=workdir))
    try:
        for n, part in enumerate(parts):
            src = tmp / "compacted.parquet"
            src.write_bytes(bucket.get(part))
            with duckdb.connect() as con:
                con.execute("SET memory_limit = '256MB'")
                con.execute("SET threads = 1")
                cur = con.execute(
                    "SELECT strftime(timezone('UTC', fetched_at), '%Y-%m-%dT%H:%M:%S.%fZ'), "
                    "content_hash, payload FROM read_parquet(?)",  # stored in time order
                    [str(src)],
                )
                chunk = 0
                while batch := cur.fetchmany(_CHUNK):
                    # Flush every _CHUNK snapshots: a whole trip-update part as NDJSON would
                    # be about 2.5 GB of temp file.
                    files: dict[str, TextIO] = {t: (tmp / f"{t}.ndjson").open("w") for t in tables}
                    try:
                        for fetched_at, sha, payload in batch:
                            _decode_snapshot(feed, fetched_at, sha, payload, files, stats)
                    finally:
                        for f in files.values():
                            f.close()
                    for t in tables:
                        key = f"{output_prefix(t, feed, day)}run={run}/part-{n}-{chunk}.parquet"
                        bucket.put(key, _to_parquet(tmp / f"{t}.ndjson", COLUMNS[t], tmp))
                        written[t].append(key)
                    chunk += 1
            src.unlink()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    marker = {
        "feed": feed, "day": day.isoformat(), "run": run, "part_keys": written,
        "snapshots": stats.snapshots, "frames": stats.frames, "rows": stats.rows,
        "quarantined": stats.quarantined, "reasons": dict(sorted(stats.reasons.items())),
        "fingerprints": len(stats.fingerprints), "decoder_version": DECODER_VERSION,
        "compaction_run": source["run"], "compactor_version": source["compactor_version"],
    }  # fmt: skip
    marker_key = _marker_key(feed, day)
    bucket.put(marker_key, json.dumps(marker, sort_keys=True).encode())
    for stale in sorted(before - {k for ks in written.values() for k in ks} - {marker_key}):
        bucket.delete(stale)
    return marker


def _to_parquet(ndjson: Path, columns: dict[str, str], tmp: Path) -> bytes:
    out = tmp / "out.parquet"
    spec = ", ".join(f"'{c}': '{t}'" for c, t in columns.items())
    select = ", ".join(f'"{c}"' for c in columns)
    with duckdb.connect() as con:
        con.execute("SET memory_limit = '512MB'")
        con.execute("SET TimeZone = 'UTC'")
        if ndjson.stat().st_size:
            source = (
                f"read_json(?, format = 'newline_delimited', columns = {{{spec}}}, "
                "auto_detect = false)"
            )
            params: list[str] = [str(ndjson), str(out)]
        else:  # an empty table still gets its typed schema
            source = f"(SELECT {', '.join(f'CAST(NULL AS {t}) AS "{c}"' for c, t in columns.items())} WHERE false)"  # noqa: E501
            params = [str(out)]
        con.execute(f"COPY (SELECT {select} FROM {source}) TO ? (FORMAT parquet)", params)  # noqa: S608
    data = out.read_bytes()
    out.unlink()
    return data


def main() -> None:  # pragma: no cover - thin CLI over tested functions
    """uv run python -m ghostbus_decode.decode --bucket <data bucket> --day YYYY-MM-DD"""
    import argparse
    import sys

    import boto3

    from ghostbus_decode.s3 import S3Bucket

    parser = argparse.ArgumentParser(description="Decode one compacted UTC day.")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--day", required=True, type=date.fromisoformat)
    parser.add_argument("--feed", choices=STREAM_FEEDS, action="append")
    args = parser.parse_args()
    bucket = S3Bucket(boto3.client("s3", region_name="us-west-2"), args.bucket)
    quarantined = 0
    for feed in args.feed or STREAM_FEEDS:
        m = decode_day(bucket, feed, args.day)
        quarantined += m["quarantined"]
        print(f"{feed} {args.day}: {m['snapshots']} snapshots, {m['frames']:,} frames, "
              f"{m['rows']:,} rows, {m['quarantined']} quarantined {m['reasons'] or ''}, "
              f"{m['fingerprints']} schema fingerprint(s)")  # fmt: skip

    if quarantined:
        sys.exit(f"{quarantined} frame(s) quarantined: see derived/decoded/_quarantine/")


if __name__ == "__main__":  # pragma: no cover
    main()
