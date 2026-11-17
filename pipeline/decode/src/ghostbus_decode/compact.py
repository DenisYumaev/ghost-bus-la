"""Compaction: one closed UTC day of snapshots into a few Parquet files per feed
(pipeline spec, section 3).

About 2,880 vehicle-position and 1,440 trip-update objects a day become
`derived/compacted/<feed>/dt=<day>/run=<id>/part-<n>.parquet`, one row per snapshot fetch:
`fetched_at`, `outcome`, `content_hash`, `object_key`, `partial`, `n_entities`, and
`payload`, the stored gzip bytes exactly as in bronze. The originals stay in bronze forever.

**Rows come from the fetch log, not the listing.** Content-addressed storage keeps identical
bytes once, but the same bytes cut at two times are two observations, and those minutes of
coverage are what separate `unknown` from `missed` later. Each row's bytes are found by hash
among that day's and the previous day's objects (a `duplicate` just after midnight repeats
bytes stored the day before). A fetch whose object never reached S3 is listed in the marker
as `missing_objects`; the fetch-log hours present, the lines read and any unparseable lines
are recorded too, so an incomplete log is visible rather than silently short.

**Readers use the marker, never a glob.** Each run writes a fresh `run=<id>/` folder, then
`_SUCCESS` listing exactly its part files, then deletes older runs. A crash at any point
leaves the previous marker pointing at its complete run; a reader that follows the marker
never sees a half-written or mixed day. Part files hold at most 200 snapshots or 64 MB:
DuckDB's Parquet writer buffered the whole BLOB column (512 MiB for a day of trip updates).

Every run rebuilds the day from bronze (hard rule 2): the same inputs give the same rows in
the same order.
"""

import json
import shutil
import tempfile
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import duckdb

from ghostbus_decode.s3 import Bucket, ReadBucket

COMPACTOR_VERSION = 2
STREAM_FEEDS = ("vehicle_positions", "trip_updates")
SUCCESS = "_SUCCESS"
FETCH_LOG_PREFIX = "bronze/_fetch_log/"
SETTLE = timedelta(hours=1)  # after midnight UTC, for the last fetch-log hour to upload
_CONTENT = ("written", "duplicate")
_PART_ROWS = 200  # snapshots per Parquet file
_PART_BYTES = 64_000_000  # ...or this many stored bytes, whichever comes first
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


@dataclass
class LogScan:
    rows: list[dict[str, Any]] = field(default_factory=list)
    lines: int = 0
    bad_lines: int = 0


def fetch_rows(lines: Iterable[str], feed: str, day: date) -> LogScan:
    """The day's content-bearing fetches for one feed, each once, ordered by time.

    Sorted by the parsed time, not the text: '12:00:00.400Z' sorts before '12:00:00Z' as
    text. The whole line breaks ties, so the order never depends on set iteration.
    """
    prefix = day.isoformat()
    scan = LogScan()
    keyed = []
    for line in set(lines):  # union of an hour's files: a re-uploaded hour repeats lines
        scan.lines += 1
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            scan.bad_lines += 1
            continue
        if (
            isinstance(rec, dict) and rec.get("event") == "fetch" and rec.get("feed") == feed
            and rec.get("outcome") in _CONTENT and str(rec.get("fetched_at", "")).startswith(prefix)
            and rec.get("content_hash")
        ):  # fmt: skip
            keyed.append((datetime.fromisoformat(rec["fetched_at"]), line, rec))
    scan.rows = [rec for _, _, rec in sorted(keyed, key=lambda k: (k[0], k[1]))]
    return scan


def compact_day(
    bucket: Bucket, feed: str, day: date, workdir: Path | None = None, workers: int = 8,
    run_id: str | None = None,
) -> dict[str, Any]:  # fmt: skip
    if feed not in STREAM_FEEDS:
        raise ValueError(f"not a stream feed: {feed!r}")
    lines: list[str] = []
    hours = set()
    for key in bucket.list_keys(f"{FETCH_LOG_PREFIX}dt={day.isoformat()}/"):
        hours.add(key.split("/hour=", 1)[1][:2])
        lines.extend(x for x in bucket.get(key).decode().splitlines() if x.strip())
    scan = fetch_rows(lines, feed, day)
    index: dict[str, str] = {}
    for d in (day - timedelta(days=1), day):  # same day wins: written last
        for key in bucket.list_keys(f"bronze/{feed}/dt={d.isoformat()}/"):
            index[key.rsplit("/", 1)[-1].split(".", 1)[0]] = key
    found = [(r, index[h]) for r in scan.rows if (h := r["content_hash"][:16]) in index]
    missing = sorted({r["content_hash"] for r in scan.rows if r["content_hash"][:16] not in index})

    prefix = day_prefix(feed, day)
    run = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    before = set(bucket.list_keys(prefix))
    tmp = Path(tempfile.mkdtemp(dir=workdir))
    try:
        parts = _write_parts(bucket, feed, found, f"{prefix}run={run}/", tmp, workers)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    marker = {
        "feed": feed, "day": day.isoformat(), "rows": len(found), "run": run,
        "part_keys": parts, "missing_objects": missing,
        "fetch_log_hours": sorted(hours),
        "missing_fetch_log_hours": sorted({f"{h:02d}" for h in range(24)} - hours),
        "fetch_log_lines": scan.lines, "bad_lines": scan.bad_lines,
        "compactor_version": COMPACTOR_VERSION,
    }  # fmt: skip
    bucket.put(prefix + SUCCESS, json.dumps(marker, sort_keys=True).encode())
    for stale in sorted(before - set(parts) - {prefix + SUCCESS}):  # older runs, after the switch
        bucket.delete(stale)
    return marker


def compaction_marker(bucket: ReadBucket, feed: str, day: date) -> dict[str, Any] | None:
    """The day's last complete compaction marker, or None."""
    key = day_prefix(feed, day) + SUCCESS
    if key not in bucket.list_keys(day_prefix(feed, day)):
        return None
    marker: dict[str, Any] = json.loads(bucket.get(key))
    return marker


def compacted_parts(bucket: ReadBucket, feed: str, day: date) -> list[str]:
    """The part files of the day's last complete run, from its marker; [] if none."""
    marker = compaction_marker(bucket, feed, day)
    return [] if marker is None else list(marker["part_keys"])


def _batches(found: list[tuple[dict[str, Any], str]]) -> list[list[tuple[dict[str, Any], str]]]:
    """Cut by row count and by stored bytes, so a part stays small if snapshots grow."""
    batches: list[list[tuple[dict[str, Any], str]]] = [[]]
    size = 0
    for item in found:
        nbytes = int(item[0].get("bytes_gz") or 0)
        if batches[-1] and (len(batches[-1]) >= _PART_ROWS or size + nbytes > _PART_BYTES):
            batches.append([])
            size = 0
        batches[-1].append(item)
        size += nbytes
    return batches


def _write_parts(
    bucket: Bucket, feed: str, found: list[tuple[dict[str, Any], str]], prefix: str, tmp: Path,
    workers: int,
) -> list[str]:  # fmt: skip
    keys_out = []
    with ThreadPoolExecutor(workers) as pool:
        for n, batch in enumerate(_batches(found)):
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


def check_closed(day: date, now: datetime) -> None:
    """Refuse a day until an hour after it ends (UTC): its last fetch-log hour uploads when
    the hour closes, and a run at 00:00:05 would silently miss it."""
    ready = datetime.combine(day + timedelta(days=1), time(0), tzinfo=UTC) + SETTLE
    if now < ready:
        raise ValueError(f"{day} is not closed yet: compact it after {ready:%Y-%m-%d %H:%M} UTC")


def main() -> None:  # pragma: no cover - thin CLI over tested functions
    """uv run python -m ghostbus_decode.compact --bucket <data bucket> --day YYYY-MM-DD"""
    import argparse
    import sys

    import boto3

    from ghostbus_decode.s3 import S3Bucket

    parser = argparse.ArgumentParser(description="Compact one closed UTC day of snapshots.")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--day", required=True, type=date.fromisoformat)
    parser.add_argument("--feed", choices=STREAM_FEEDS, action="append")
    args = parser.parse_args()
    check_closed(args.day, datetime.now(UTC))
    bucket = S3Bucket(boto3.client("s3", region_name="us-west-2"), args.bucket)
    problems = 0
    for feed in args.feed or STREAM_FEEDS:
        m = compact_day(bucket, feed, args.day)
        problems += len(m["missing_objects"]) + m["bad_lines"]
        print(f"{feed} {args.day}: {m['rows']} snapshots in {len(m['part_keys'])} parts; "
              f"{len(m['missing_objects'])} missing objects; {m['bad_lines']} bad log lines; "
              f"fetch-log hours missing: {m['missing_fetch_log_hours'] or 'none'}")  # fmt: skip
    if problems:
        sys.exit(f"{problems} problem(s): see above")


if __name__ == "__main__":  # pragma: no cover
    main()
