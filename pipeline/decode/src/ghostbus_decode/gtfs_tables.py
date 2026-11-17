"""Extract one schedule version's tables to typed Parquet (pipeline spec, sections 3 and 4).

Each table lands at `derived/decoded/gtfs/<version>/<table>.parquet`, every row stamped
with `schedule_version`. Columns are kept as published (text), except a few that are typed
in place (dates, numbers) and the two times, which keep their text and gain a `_s` column of
GTFS seconds (`arrival_s`, `departure_s`). Identifiers stay text: line names include `10/48`.

A value that fails to parse refuses the whole version, with an example, and nothing marks it
done; decode never drops a record silently. `_SUCCESS` is written last, so a version with it
is complete and is skipped on later runs; a crash midway leaves no `_SUCCESS`, and the next
run rewrites every table.

DuckDB reads the CSVs from disk, so the 307 MB `stop_times.txt` never sits in Python memory.
`shapes.txt` (18 MB) and the fare tables aren't needed yet and aren't extracted.
"""

import json
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import duckdb

from ghostbus_decode.gtfs_sql import gtfs_seconds_sql
from ghostbus_decode.s3 import Bucket

GTFS_DERIVED = "derived/decoded/gtfs/"
SUCCESS = "_SUCCESS"
_VERSION = re.compile(r"[0-9a-f]{16}")
_COLUMN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


class MissingTable(Exception):
    """A table every version must have is absent from the ZIP."""


class BadGtfsValue(Exception):
    """A value didn't parse; the version is refused rather than loaded with gaps."""


@dataclass(frozen=True)
class Table:
    required: bool
    typed: dict[str, str]  # column -> int | double | date | time


TABLES = {
    "routes": Table(True, {"route_type": "int"}),
    "trips": Table(True, {"direction_id": "int"}),
    "stops": Table(True, {"stop_lat": "double", "stop_lon": "double", "location_type": "int"}),
    "stop_times": Table(
        True,
        {
            "arrival_time": "time",
            "departure_time": "time",
            "stop_sequence": "int",
            "pickup_type": "int",
            "drop_off_type": "int",
            "timepoint": "int",
        },
    ),
    "calendar": Table(
        False, {**dict.fromkeys(_WEEKDAYS, "int"), "start_date": "date", "end_date": "date"}
    ),
    "calendar_dates": Table(False, {"date": "date", "exception_type": "int"}),
    "feed_info": Table(False, {"feed_start_date": "date", "feed_end_date": "date"}),
}


def version_prefix(version_id: str) -> str:
    if _VERSION.fullmatch(version_id) is None:
        raise ValueError(f"not a version id: {version_id!r}")
    return f"{GTFS_DERIVED}{version_id}/"


def extract_version(
    bucket: Bucket, version_id: str, zip_key: str, workdir: Path | None = None
) -> dict[str, object] | None:
    """Extract every table of one version; None if it was already complete."""
    prefix = version_prefix(version_id)
    if prefix + SUCCESS in bucket.list_keys(prefix):
        return None
    tmp = Path(tempfile.mkdtemp(dir=workdir))
    try:
        rows = _extract(bucket, version_id, zip_key, prefix, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    marker: dict[str, object] = {"schedule_version": version_id, "source": zip_key, "rows": rows}
    bucket.put(prefix + SUCCESS, json.dumps(marker, sort_keys=True).encode())
    return marker


def _extract(bucket: Bucket, version: str, zip_key: str, prefix: str, tmp: Path) -> dict[str, int]:
    zip_path = tmp / "gtfs.zip"
    zip_path.write_bytes(bucket.get(zip_key))
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        missing = [
            f"{t}.txt" for t, spec in TABLES.items() if spec.required and f"{t}.txt" not in names
        ]
        if missing:
            raise MissingTable(f"{zip_key}: missing {', '.join(missing)}")
        if not {"calendar.txt", "calendar_dates.txt"} & names:
            raise MissingTable(f"{zip_key}: needs calendar.txt or calendar_dates.txt")
        rows: dict[str, int] = {}
        with duckdb.connect() as con:
            for table, spec in TABLES.items():
                if f"{table}.txt" not in names:
                    continue
                csv_path = tmp / f"{table}.txt"
                with zf.open(f"{table}.txt") as src, csv_path.open("wb") as dst:
                    shutil.copyfileobj(src, dst)  # our own path: no zip-slip
                out = tmp / f"{table}.parquet"
                rows[table] = _convert(con, table, spec, csv_path, out, version)
                bucket.put(f"{prefix}{table}.parquet", out.read_bytes())
                csv_path.unlink()
    return rows


def _convert(
    con: duckdb.DuckDBPyConnection, table: str, spec: Table, src: Path, out: Path, version: str
) -> int:
    con.execute(f"DROP TABLE IF EXISTS raw_{table}")
    con.execute(
        f"CREATE TABLE raw_{table} AS SELECT * FROM read_csv(?, header = true, "  # noqa: S608
        "all_varchar = true, delim = ',', quote = '\"', escape = '\"', auto_detect = true)",
        [str(src)],
    )
    columns = [r[0] for r in con.execute(f"DESCRIBE raw_{table}").fetchall()]
    for c in columns:
        if _COLUMN.fullmatch(c) is None:
            raise BadGtfsValue(f"{table}: unexpected column name {c!r}")
    select = []
    for c in columns:
        kind = spec.typed.get(c)
        if kind == "time":
            select += [c, f"{gtfs_seconds_sql(c)} AS {c.removesuffix('_time')}_s"]
            _check(con, table, c, gtfs_seconds_sql(c))
        elif kind is not None:
            expr = _typed(c, kind)
            select.append(f"{expr} AS {c}")
            _check(con, table, c, expr)
        else:
            select.append(c)
    select.append(f"'{version}' AS schedule_version")
    con.execute(
        f"COPY (SELECT {', '.join(select)} FROM raw_{table}) TO ? (FORMAT parquet)",  # noqa: S608
        [str(out)],
    )
    count = con.execute(f"SELECT count(*) FROM raw_{table}").fetchall()[0][0]  # noqa: S608
    return int(count)


def _typed(column: str, kind: str) -> str:
    v = f"nullif(trim({column}), '')"
    if kind == "int":
        return f"TRY_CAST({v} AS INTEGER)"
    if kind == "double":
        return f"TRY_CAST({v} AS DOUBLE)"
    if kind == "date":
        parsed = f"CAST(try_strptime({v}, '%Y%m%d') AS DATE)"
        return f"CASE WHEN regexp_full_match({v}, '[0-9]{{8}}') THEN {parsed} END"
    raise ValueError(f"unknown kind {kind!r}")  # pragma: no cover - TABLES is a constant


def _check(con: duckdb.DuckDBPyConnection, table: str, column: str, expr: str) -> None:
    """Refuse the version if any non-blank value failed to parse; name one example."""
    bad = con.execute(
        f"SELECT count(*), min({column}) FROM raw_{table} "  # noqa: S608
        f"WHERE nullif(trim({column}), '') IS NOT NULL AND ({expr}) IS NULL"
    ).fetchall()[0]
    if bad[0]:
        raise BadGtfsValue(f"{table}.{column}: {bad[0]} value(s) didn't parse, e.g. {bad[1]!r}")


def load_gtfs(bucket: Bucket, workdir: Path | None = None) -> list[str]:
    """Rebuild `dim_schedule_version`, then extract every version not yet complete.

    Superseded versions are extracted too: rows matched against them must still resolve.
    Returns report lines.
    """
    from ghostbus_decode.gtfs_versions import report, write_dim

    build = write_dim(bucket)
    lines = [report(build)]
    for v in build.versions:
        marker = extract_version(bucket, v.version_id, build.zip_keys[v.version_id], workdir)
        if marker is None:
            lines.append(f"  {v.version_id}: already extracted")
        else:
            rows = cast("dict[str, int]", marker["rows"])
            counts = ", ".join(f"{t} {n:,}" for t, n in sorted(rows.items()))
            lines.append(f"  {v.version_id}: extracted {counts}")
    return lines


def main() -> None:  # pragma: no cover - thin CLI over tested functions
    """uv run python -m ghostbus_decode.gtfs_tables --bucket <data bucket>"""
    import argparse

    import boto3

    from ghostbus_decode.s3 import S3Bucket

    parser = argparse.ArgumentParser(description="Load GTFS versions from bronze into derived/.")
    parser.add_argument("--bucket", required=True)
    args = parser.parse_args()
    bucket = S3Bucket(boto3.client("s3", region_name="us-west-2"), args.bucket)
    print("\n".join(load_gtfs(bucket)))


if __name__ == "__main__":  # pragma: no cover
    main()
