"""Copy what dbt needs from S3 to a local folder (`data/` by default).

dbt-duckdb reads the local copy, not S3: readers must follow `_SUCCESS` markers (never glob
a prefix that may hold a half-written or stale run), and this keeps S3 credentials out of
DuckDB. The local folder holds only marker-listed files, so dbt can glob it safely.

For service dates `start..end` it copies, for UTC days `start..end+1` (a service date's
trips run past midnight Los Angeles, which is the next UTC day):

- `decoded/<table>/dt=<day>/*.parquet` for `vehicle_position` and `trip_update`;
- `fetch_log/dt=<day>/hour=HH-<name>.jsonl`, the raw fetch-log hour files;
- `gtfs/dim_schedule_version.parquet` and every schedule version whose `_SUCCESS` matches
  the current extractor, as `gtfs/<version>/<table>.parquet`.

Each day's folder is replaced wholesale, so a resync never leaves an older run's files.
Read-only on S3.
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


def utc_days_for(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 2)]


def _replace_dir(path: Path) -> Path:
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True)
    return path


def sync(bucket: ReadBucket, start: date, end: date, dest: Path) -> dict[str, Any]:
    report: dict[str, Any] = {"missing": {t: [] for t in FEEDS}, "files": 0}
    for day in utc_days_for(start, end):
        for table, feed in FEEDS.items():
            parts = decoded_parts(bucket, feed, day).get(table)
            if parts is None:
                report["missing"][table].append(day.isoformat())
                continue
            out = _replace_dir(dest / "decoded" / table / f"dt={day.isoformat()}")
            for key in parts:
                (out / key.rsplit("/", 1)[-1]).write_bytes(bucket.get(key))
                report["files"] += 1
        logs = _replace_dir(dest / "fetch_log" / f"dt={day.isoformat()}")
        for key in bucket.list_keys(f"bronze/_fetch_log/dt={day.isoformat()}/"):
            hour, name = key.rsplit("/", 2)[-2:]
            (logs / f"{hour}-{name}").write_bytes(bucket.get(key))
            report["files"] += 1
    _sync_gtfs(bucket, dest / "gtfs", report)
    return report


def _sync_gtfs(bucket: ReadBucket, dest: Path, report: dict[str, Any]) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    dim = f"{GTFS_DERIVED}dim_schedule_version.parquet"
    keys = bucket.list_keys(GTFS_DERIVED)
    if dim in keys:
        (dest / "dim_schedule_version.parquet").write_bytes(bucket.get(dim))
    versions = sorted(
        {k[len(GTFS_DERIVED) :].split("/", 1)[0] for k in keys if k.endswith(SUCCESS)}
    )
    report["gtfs_versions"], report["gtfs_not_extracted"] = [], []
    for v in versions:
        if not is_extracted(bucket, v):
            report["gtfs_not_extracted"].append(v)
            continue
        out = _replace_dir(dest / v)
        for key in bucket.list_keys(f"{GTFS_DERIVED}{v}/"):
            if key.endswith(".parquet"):
                (out / key.rsplit("/", 1)[-1]).write_bytes(bucket.get(key))
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
