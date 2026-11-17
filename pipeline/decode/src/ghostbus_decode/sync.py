"""Copy what dbt needs from S3 to a local folder (`data/` by default).

dbt-duckdb reads the local copy, not S3: readers must follow `_SUCCESS` markers (never glob
a prefix that may hold a half-written or stale run), and this keeps S3 credentials out of
DuckDB (ADR-023). The local folder holds exactly the marker-listed files for the synced
range, so dbt can glob it safely.

For service dates `start..end` it copies UTC days `start-1..end+1`: a service date's trips
run past midnight Los Angeles (the next UTC day), and a cancellation can be announced hours
ahead (the previous UTC day for early trips). Per UTC day: `decoded/<table>/dt=<day>/` for
`vehicle_position` and `trip_update`, and `fetch_log/dt=<day>/`. Plus
`gtfs/dim_schedule_version.parquet` and the tables each extracted version's `_SUCCESS`
lists, as `gtfs/<version>/<table>.parquet`.

**All or nothing.** Everything is built in `<dest>/.staging/` and swapped in only when the
whole range is complete, so an interrupted sync leaves the previous copy intact, and nothing
outside the requested range survives (no stale days or versions). A UTC day without both
decoded tables fails the sync: copying its fetch log alone would make that day's trips look
unobserved, hence missed. Read-only on S3.
"""

import json
import shutil
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from ghostbus_decode.decode import decoded_parts
from ghostbus_decode.gtfs_tables import GTFS_DERIVED, SUCCESS, is_extracted
from ghostbus_decode.s3 import ReadBucket

FEEDS = {"vehicle_position": "vehicle_positions", "trip_update": "trip_updates"}
_TREES = ("decoded", "fetch_log", "gtfs")


class IncompleteRange(Exception):
    """A UTC day in the range isn't decoded yet; nothing was changed locally."""


def utc_days_for(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range(-1, (end - start).days + 2)]


def sync(bucket: ReadBucket, start: date, end: date, dest: Path) -> dict[str, Any]:
    days = utc_days_for(start, end)
    plan: dict[date, dict[str, list[str]]] = {}
    missing: dict[str, list[str]] = {t: [] for t in FEEDS}
    for day in days:
        found = {t: decoded_parts(bucket, feed, day).get(t) for t, feed in FEEDS.items()}
        for t, parts in found.items():
            if parts is None:
                missing[t].append(day.isoformat())
        plan[day] = {t: p for t, p in found.items() if p is not None}
    if any(missing.values()):
        raise IncompleteRange(
            f"not decoded (or decoded by an older decoder): {missing}; run make decode"
        )

    staging = dest / ".staging"
    shutil.rmtree(staging, ignore_errors=True)
    report: dict[str, Any] = {"days": [d.isoformat() for d in days], "files": 0}
    for day, tables in plan.items():
        for table, parts in tables.items():
            out = staging / "decoded" / table / f"dt={day.isoformat()}"
            out.mkdir(parents=True)
            for key in parts:
                (out / key.rsplit("/", 1)[-1]).write_bytes(bucket.get(key))
                report["files"] += 1
        logs = staging / "fetch_log" / f"dt={day.isoformat()}"
        logs.mkdir(parents=True)
        for key in bucket.list_keys(f"bronze/_fetch_log/dt={day.isoformat()}/"):
            hour, name = key.rsplit("/", 2)[-2:]
            (logs / f"{hour}-{name}").write_bytes(bucket.get(key))
            report["files"] += 1
    _sync_gtfs(bucket, staging / "gtfs", report)

    for tree in _TREES:  # swap in only now that the whole range is complete
        shutil.rmtree(dest / tree, ignore_errors=True)
        (staging / tree).rename(dest / tree)
    staging.rmdir()
    summary = {"start": start.isoformat(), "end": end.isoformat(), **report}
    (dest / "_sync.json").write_text(json.dumps(summary, indent=2))
    return report


def _sync_gtfs(bucket: ReadBucket, dest: Path, report: dict[str, Any]) -> None:
    dest.mkdir(parents=True)
    dim = f"{GTFS_DERIVED}dim_schedule_version.parquet"
    keys = bucket.list_keys(GTFS_DERIVED)
    if dim in keys:
        (dest / "dim_schedule_version.parquet").write_bytes(bucket.get(dim))
    markers = [k for k in keys if k.endswith(SUCCESS)]
    versions = sorted({k[len(GTFS_DERIVED) :].split("/", 1)[0] for k in markers})
    report["gtfs_versions"], report["gtfs_not_extracted"] = [], []
    for v in versions:
        if not is_extracted(bucket, v):
            report["gtfs_not_extracted"].append(v)
            continue
        rows = json.loads(bucket.get(f"{GTFS_DERIVED}{v}/{SUCCESS}"))["rows"]
        out = dest / v
        out.mkdir()
        for table in sorted(rows):  # only the tables this extraction wrote
            key = f"{GTFS_DERIVED}{v}/{table}.parquet"
            (out / f"{table}.parquet").write_bytes(bucket.get(key))
        report["gtfs_versions"].append(v)


def main() -> None:  # pragma: no cover - thin CLI over tested functions
    """uv run python -m ghostbus_decode.sync --bucket <bucket> --start D --end D [--dest data]"""
    import argparse

    import boto3

    from ghostbus_decode.s3 import S3Bucket

    parser = argparse.ArgumentParser(description="Copy derived data for dbt to a local folder.")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--dest", default="data", type=Path)
    args = parser.parse_args()
    bucket = S3Bucket(boto3.client("s3", region_name="us-west-2"), args.bucket)
    report = sync(bucket, args.start, args.end, args.dest)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":  # pragma: no cover
    main()
