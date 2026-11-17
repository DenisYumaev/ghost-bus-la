"""Build `dim_schedule_version` from the GTFS ZIPs in bronze (pipeline spec, section 4).

Steps: find each stored ZIP and its first sighting (`gtfs_sightings`); read its feed dates
from `feed_info.txt`; resolve validity ranges with `ghostbus_core.schedule_versions`; write
the whole dimension as one Parquet file under `derived/`, overwriting it. The file is
rebuilt from bronze every run, so running twice gives the same result (hard rule 2).
"""

import csv
import io
import tempfile
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import duckdb
from ghostbus_core.schedule_versions import (
    VERSION_ID_LEN,
    ScheduleVersion,
    SeenZip,
    resolve_versions,
)
from ghostbus_core.service_date import parse_service_date

from ghostbus_decode.gtfs_sightings import load_sightings
from ghostbus_decode.s3 import Bucket, ReadBucket

DIM_KEY = "derived/decoded/gtfs/dim_schedule_version.parquet"

_COLUMNS = """
    version_id      VARCHAR NOT NULL,
    sha256          VARCHAR NOT NULL,
    first_seen_at   TIMESTAMPTZ NOT NULL,
    feed_start_date DATE,
    feed_end_date   DATE,
    valid_from      DATE NOT NULL,
    valid_to        DATE,
    ever_in_force   BOOLEAN NOT NULL
"""


def read_feed_dates(zip_bytes: bytes) -> tuple[date | None, date | None]:
    """`feed_start_date` and `feed_end_date` from `feed_info.txt`; None when absent or empty."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        if "feed_info.txt" not in zf.namelist():
            return None, None
        text = zf.read("feed_info.txt").decode("utf-8-sig")  # utf-8-sig drops a BOM
    rows = [
        r for r in csv.DictReader(io.StringIO(text)) if any((v or "").strip() for v in r.values())
    ]
    if not rows:
        return None, None
    if len(rows) > 1:
        raise ValueError(f"feed_info.txt should have one row, has {len(rows)}")
    row = rows[0]
    return _date(row.get("feed_start_date")), _date(row.get("feed_end_date"))


@dataclass(frozen=True)
class VersionBuild:
    versions: list[ScheduleVersion]
    waiting: list[str]  # ZIPs stored too recently to have a sighting; next run picks them up
    zip_keys: dict[str, str] = field(default_factory=dict)  # version_id -> bronze key


def build_versions(bucket: ReadBucket, today: date | None = None) -> VersionBuild:
    """Every stored version with its validity range. Reads one ZIP at a time (about 22 MB)."""
    found = load_sightings(bucket, today)
    zips = []
    for seen in found.zips:
        start, end = read_feed_dates(bucket.get(seen.object_key))
        zips.append(SeenZip(seen.sha256, seen.first_seen_at, start, end))
    keys = {z.sha256[:VERSION_ID_LEN]: z.object_key for z in found.zips}
    return VersionBuild(resolve_versions(zips), found.waiting, keys)


def versions_parquet(versions: Sequence[ScheduleVersion]) -> bytes:
    """The dimension as Parquet bytes, typed explicitly so an empty table keeps its schema."""
    rows = [
        (v.version_id, v.sha256, v.first_seen_at, v.feed_start_date, v.feed_end_date,
         v.valid_from, v.valid_to, v.ever_in_force)
        for v in versions
    ]  # fmt: skip
    with tempfile.TemporaryDirectory() as tmp, duckdb.connect() as con:
        out = Path(tmp) / "dim.parquet"
        con.execute(f"CREATE TABLE dim ({_COLUMNS})")
        if rows:
            con.executemany("INSERT INTO dim VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
        con.execute(
            "COPY (SELECT * FROM dim ORDER BY valid_from, first_seen_at) TO ? (FORMAT parquet)",
            [str(out)],
        )
        return out.read_bytes()


def write_dim(bucket: Bucket, today: date | None = None) -> VersionBuild:
    build = build_versions(bucket, today)
    bucket.put(DIM_KEY, versions_parquet(build.versions))
    return build


def _date(text: str | None) -> date | None:
    text = (text or "").strip()
    return parse_service_date(text) if text else None


def report(build: VersionBuild) -> str:
    lines = [f"{len(build.versions)} schedule version(s):"]
    for v in build.versions:
        to = v.valid_to.isoformat() if v.valid_to else "open"
        state = "" if v.ever_in_force else "  (superseded the day it took effect)"
        lines.append(
            f"  {v.version_id}  first seen {v.first_seen_at:%Y-%m-%d %H:%M}Z  "
            f"feed {v.feed_start_date}..{v.feed_end_date}  valid {v.valid_from}..{to}{state}"
        )
    lines += [f"  waiting for its fetch-log hour (next run): {k}" for k in build.waiting]
    return "\n".join(lines)


def main() -> None:  # pragma: no cover - thin CLI over tested functions
    """uv run python -m ghostbus_decode.gtfs_versions --bucket <data bucket> [--dry-run]"""
    import argparse

    import boto3

    from ghostbus_decode.s3 import S3Bucket

    parser = argparse.ArgumentParser(description="Build dim_schedule_version from bronze.")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--dry-run", action="store_true", help="print, don't write")
    args = parser.parse_args()
    bucket = S3Bucket(boto3.client("s3", region_name="us-west-2"), args.bucket)
    build = build_versions(bucket) if args.dry_run else write_dim(bucket)
    print(report(build))
    if not args.dry_run:
        print(f"wrote s3://{args.bucket}/{DIM_KEY}")


if __name__ == "__main__":  # pragma: no cover
    main()
