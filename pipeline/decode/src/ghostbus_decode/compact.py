"""Compaction: one UTC day of snapshots into one Parquet file per feed (pipeline spec, section 3).

About 2,880 vehicle-position and 1,440 trip-update objects a day become
`derived/compacted/<feed>/dt=<day>/part-<n>.parquet` (200 snapshots per file, so memory
stays bounded; readers glob the day), one row per snapshot fetch:
`fetched_at`, `outcome`, `content_hash`, `object_key`, `partial`, `n_entities`, and
`payload`, the stored gzip bytes exactly as in bronze. The originals stay in bronze forever.

Rows come from the fetch log, not the listing: content-addressed storage keeps identical
bytes once, but the same bytes cut at two times are two observations, and those minutes of
coverage are what separate `unknown` from `missed` later. Each row's bytes are found by hash
among that day's and the previous day's objects (a `duplicate` just after midnight repeats
bytes stored the day before); a fetch whose object never reached S3 is listed in the marker
as `missing_objects`, never hidden.

The whole day is rewritten on every run (hard rule 2), so running twice gives the same file.
Compact closed days only (before today, UTC): the open day's fetch log isn't complete.
"""

import json
import shutil
import tempfile
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from ghostbus_decode.s3 import Bucket

COMPACTOR_VERSION = 1
STREAM_FEEDS = ("vehicle_positions", "trip_updates")
SUCCESS = "_SUCCESS"
FETCH_LOG_PREFIX = "bronze/_fetch_log/"
_CONTENT = ("written", "duplicate")
_PART_ROWS = 200  # snapshots per Parquet file: about 50 MB of trip updates
_COLUMNS = """
    feed         VARCHAR NOT NULL,
    fetched_at   TIMESTAMPTZ NOT NULL,
    outcome      VARCHAR NOT NULL,
    content_hash VARCHAR NOT NULL,
    object_key   VARCHAR NOT NULL,
    partial      BOOLEAN,
    n_entities   INTEGER,
    payload      BLOB NOT NULL
"""


def day_prefix(feed: str, day: date) -> str:
    return f"derived/compacted/{feed}/dt={day.isoformat()}/"


def compacted_key(feed: str, day: date, part: int = 0) -> str:
    return f"{day_prefix(feed, day)}part-{part}.parquet"


def fetch_rows(lines: Iterable[str], feed: str, day: date) -> list[dict[str, Any]]:
    """The day's content-bearing fetches for one feed, each once, ordered by time."""
    prefix = day.isoformat()
    rows = []
    for line in set(lines):  # union of an hour's files: a re-uploaded hour repeats lines
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(rec, dict) and rec.get("event") == "fetch" and rec.get("feed") == feed
            and rec.get("outcome") in _CONTENT and str(rec.get("fetched_at", "")).startswith(prefix)
            and rec.get("content_hash")
        ):  # fmt: skip
            rows.append(rec)
    return sorted(rows, key=lambda r: (r["fetched_at"], r["outcome"], r["content_hash"]))


def compact_day(
    bucket: Bucket, feed: str, day: date, workdir: Path | None = None, workers: int = 8
) -> dict[str, Any]:
    if feed not in STREAM_FEEDS:
        raise ValueError(f"not a stream feed: {feed!r}")
    lines: list[str] = []
    for key in bucket.list_keys(f"{FETCH_LOG_PREFIX}dt={day.isoformat()}/"):
        lines.extend(x for x in bucket.get(key).decode().splitlines() if x.strip())
    rows = fetch_rows(lines, feed, day)
    index: dict[str, str] = {}
    for d in (day - timedelta(days=1), day):  # same day wins: written last
        for key in bucket.list_keys(f"bronze/{feed}/dt={d.isoformat()}/"):
            index[key.rsplit("/", 1)[-1].split(".", 1)[0]] = key
    found = [(r, index[r["content_hash"][:16]]) for r in rows if r["content_hash"][:16] in index]
    missing = sorted({r["content_hash"] for r in rows if r["content_hash"][:16] not in index})

    prefix = day_prefix(feed, day)
    old = {k for k in bucket.list_keys(prefix) if k.endswith(".parquet")}
    tmp = Path(tempfile.mkdtemp(dir=workdir))
    try:
        parts = _write_parts(bucket, feed, found, prefix, tmp, workers)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for stale in sorted(old - set(parts)):  # a rerun with fewer rows leaves no extra parts
        bucket.delete(stale)
    marker = {
        "feed": feed, "day": day.isoformat(), "rows": len(found), "parts": len(parts),
        "missing_objects": missing, "compactor_version": COMPACTOR_VERSION,
    }  # fmt: skip
    bucket.put(prefix + SUCCESS, json.dumps(marker, sort_keys=True).encode())
    return marker


def _write_parts(
    bucket: Bucket, feed: str, found: list[tuple[dict[str, Any], str]], prefix: str, tmp: Path,
    workers: int,
) -> list[str]:  # fmt: skip
    """Write `_PART_ROWS` snapshots per file. Bounded files keep memory bounded: DuckDB's
    Parquet writer allocated a buffer the size of the whole BLOB column (512 MiB for one day
    of trip updates), which no row-group setting avoided."""
    keys_out = []
    batches = [found[i : i + _PART_ROWS] for i in range(0, len(found), _PART_ROWS)] or [[]]
    with ThreadPoolExecutor(workers) as pool:
        for n, batch in enumerate(batches):
            keys = sorted({key for _, key in batch})
            payloads = dict(zip(keys, pool.map(bucket.get, keys), strict=True))
            out = tmp / f"part-{n}.parquet"
            with duckdb.connect() as con:
                con.execute("SET memory_limit = '512MB'")
                con.execute(f"CREATE TABLE snaps ({_COLUMNS})")
                if batch:
                    con.executemany(
                        "INSERT INTO snaps VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        [
                            (feed, datetime.fromisoformat(r["fetched_at"]), r["outcome"],
                             r["content_hash"], key, r.get("partial"), r.get("n_entities"),
                             payloads[key])
                            for r, key in batch
                        ],
                    )  # fmt: skip
                # Inserted in time order already, so no ORDER BY.
                con.execute("COPY snaps TO ? (FORMAT parquet)", [str(out)])
            key = f"{prefix}part-{n}.parquet"
            bucket.put(key, out.read_bytes())
            out.unlink()
            keys_out.append(key)
    return keys_out


def check_closed(day: date, today: date) -> None:
    """Refuse the open UTC day: its fetch log isn't complete until the day ends."""
    if day >= today:
        raise ValueError(f"{day} is not closed yet (today is {today}, UTC)")


def main() -> None:  # pragma: no cover - thin CLI over tested functions
    """uv run python -m ghostbus_decode.compact --bucket <data bucket> --day YYYY-MM-DD"""
    import argparse
    import sys
    from datetime import UTC

    import boto3

    from ghostbus_decode.s3 import S3Bucket

    parser = argparse.ArgumentParser(description="Compact one closed UTC day of snapshots.")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--day", required=True, type=date.fromisoformat)
    parser.add_argument("--feed", choices=STREAM_FEEDS, action="append")
    args = parser.parse_args()
    check_closed(args.day, datetime.now(UTC).date())
    bucket = S3Bucket(boto3.client("s3", region_name="us-west-2"), args.bucket)
    missing = 0
    for feed in args.feed or STREAM_FEEDS:
        marker = compact_day(bucket, feed, args.day)
        missing += len(marker["missing_objects"])
        print(f"{feed} {args.day}: {marker['rows']} snapshots, "
              f"{len(marker['missing_objects'])} missing objects")  # fmt: skip
    if missing:
        sys.exit(f"{missing} fetches had no object in bronze")


if __name__ == "__main__":  # pragma: no cover
    main()
