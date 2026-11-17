"""Extract one schedule version's tables to typed Parquet (pipeline spec, sections 3 and 4).

Each table lands at `derived/decoded/gtfs/<version>/<table>.parquet`, every row stamped
with `schedule_version`. Columns are kept as published (text), except a few that are typed
in place (dates, small integer codes, coordinates) and the two stop times, which keep their
text and gain a `_s` column of GTFS seconds (`arrival_s`, `departure_s`). Identifiers stay
text: line names include `10/48`. An optional typed column that a version lacks is written as
a typed NULL, so every version has the same schema.

**Strict by design.** A schedule with gaps would turn real trips into "missed" ones, so for
the schedule the rule is refuse, not quarantine (realtime decode quarantines bad rows,
section 3): any value that doesn't parse exactly, a missing required column, a duplicate
header, or a malformed row refuses the whole version, with an example. DuckDB's own casts
are too lenient for this ('2.5' becomes integer 3, 'NaN' a coordinate, a short row makes the
CSV sniffer change delimiter), so every value is checked against an exact pattern first and
the CSV reader runs with auto-detection off and every option pinned.

`_SUCCESS` is written last and records `EXTRACTOR_VERSION`: a version extracted by the same
extractor is skipped; an older or missing marker means a rerun rewrites every table. Readers
must use only versions that have a matching `_SUCCESS`.

DuckDB works in a database file in the temp directory with a memory limit, so the 307 MB
`stop_times.txt` never sits in Python memory and the load can't starve ingest if it ever
runs on the VM (hard rule 3). `shapes.txt` and the fare tables aren't extracted yet.
"""

import csv
import io
import json
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import duckdb

from ghostbus_decode.gtfs_sql import gtfs_seconds_sql, trim_sql
from ghostbus_decode.s3 import Bucket, ReadBucket

# Bump when the output changes (columns, typing, rules), so existing versions are redone.
EXTRACTOR_VERSION = 2
GTFS_DERIVED = "derived/decoded/gtfs/"
SUCCESS = "_SUCCESS"
MEMORY_LIMIT = "768MB"
_VERSION = re.compile(r"[0-9a-f]{16}")
_COLUMN = re.compile(r"[a-z_][a-z0-9_]*")  # GTFS names are lowercase snake_case
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_SQL_TYPE = {"int": "INTEGER", "lat": "DOUBLE", "lon": "DOUBLE", "date": "DATE"}


class MissingTable(Exception):
    """A table every version must have is absent from the ZIP."""


class BadGtfsValue(Exception):
    """A value, header, or row didn't parse; the version is refused rather than loaded."""


@dataclass(frozen=True)
class Table:
    required: bool
    columns: tuple[str, ...]  # must be present (GTFS-required, or used downstream)
    typed: dict[str, str] = field(default_factory=dict)  # column -> int|lat|lon|date|time


TABLES = {
    "routes": Table(True, ("route_id", "route_short_name", "route_type"), {"route_type": "int"}),
    "trips": Table(
        True, ("route_id", "service_id", "trip_id", "direction_id"), {"direction_id": "int"}
    ),
    "stops": Table(
        True,
        ("stop_id", "stop_name", "stop_lat", "stop_lon"),
        {"stop_lat": "lat", "stop_lon": "lon", "location_type": "int"},
    ),
    "stop_times": Table(
        True,
        ("trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"),
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
        False,
        ("service_id", *_WEEKDAYS, "start_date", "end_date"),
        {**dict.fromkeys(_WEEKDAYS, "int"), "start_date": "date", "end_date": "date"},
    ),
    "calendar_dates": Table(
        False, ("service_id", "date", "exception_type"), {"date": "date", "exception_type": "int"}
    ),
    "feed_info": Table(False, (), {"feed_start_date": "date", "feed_end_date": "date"}),
}


def version_prefix(version_id: str) -> str:
    if _VERSION.fullmatch(version_id) is None:
        raise ValueError(f"not a version id: {version_id!r}")
    return f"{GTFS_DERIVED}{version_id}/"


def is_extracted(bucket: ReadBucket, version_id: str) -> bool:
    """True if the version has a `_SUCCESS` written by this extractor version."""
    key = version_prefix(version_id) + SUCCESS
    if key not in bucket.list_keys(version_prefix(version_id)):
        return False
    try:
        marker = json.loads(bucket.get(key))
    except ValueError:
        return False
    return isinstance(marker, dict) and marker.get("extractor_version") == EXTRACTOR_VERSION


def extract_version(
    bucket: Bucket, version_id: str, zip_key: str, workdir: Path | None = None,
    *, force: bool = False,
) -> dict[str, object] | None:  # fmt: skip
    """Extract every table of one version; None if this extractor already did."""
    prefix = version_prefix(version_id)
    if not force and is_extracted(bucket, version_id):
        return None
    tmp = Path(tempfile.mkdtemp(dir=workdir))
    try:
        rows = _extract(bucket, version_id, zip_key, prefix, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    marker: dict[str, object] = {
        "schedule_version": version_id, "source": zip_key, "rows": rows,
        "extractor_version": EXTRACTOR_VERSION,
    }  # fmt: skip
    bucket.put(prefix + SUCCESS, json.dumps(marker, sort_keys=True).encode())
    return marker


def _extract(bucket: Bucket, version: str, zip_key: str, prefix: str, tmp: Path) -> dict[str, int]:
    zip_path = tmp / "gtfs.zip"
    zip_path.write_bytes(bucket.get(zip_key))
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        required = [f"{t}.txt" for t, spec in TABLES.items() if spec.required]
        missing = [name for name in required if name not in names]
        if missing:
            raise MissingTable(f"{zip_key}: missing {', '.join(missing)}")
        if not {"calendar.txt", "calendar_dates.txt"} & names:
            raise MissingTable(f"{zip_key}: needs calendar.txt or calendar_dates.txt")
        rows: dict[str, int] = {}
        with duckdb.connect(str(tmp / "load.duckdb")) as con:
            con.execute(f"SET memory_limit = '{MEMORY_LIMIT}'")
            con.execute("SET threads = 2")
            con.execute(f"SET temp_directory = '{tmp / 'spill'}'")
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
                out.unlink()
    return rows


def read_header(path: Path, table: str) -> list[str]:
    """The header row, checked: plain lowercase names, no duplicates, nothing generated."""
    with path.open(encoding="utf-8-sig", newline="") as f:
        header = next(csv.reader(io.StringIO(f.readline())), [])
    columns = [c.strip() for c in header]
    bad = [c for c in columns if _COLUMN.fullmatch(c) is None]
    if bad:
        raise BadGtfsValue(f"{table}: unexpected column name {bad[0]!r}")
    dupes = sorted({c for c in columns if columns.count(c) > 1})
    if dupes:
        raise BadGtfsValue(f"{table}: duplicate column {dupes[0]!r}")
    generated = {"schedule_version"} | {
        c.removesuffix("_time") + "_s" for c, k in TABLES[table].typed.items() if k == "time"
    }
    clash = sorted(generated & set(columns))
    if clash:
        raise BadGtfsValue(f"{table}: column {clash[0]!r} clashes with a generated column")
    return columns


def _convert(
    con: duckdb.DuckDBPyConnection, table: str, spec: Table, src: Path, out: Path, version: str
) -> int:
    columns = read_header(src, table)
    absent = [c for c in spec.columns if c not in columns]
    if absent:
        raise BadGtfsValue(f"{table}: missing required column {absent[0]!r}")
    types = ", ".join(f"'{c}': 'VARCHAR'" for c in columns)
    raw = f"raw_{table}"
    con.execute(f"DROP TABLE IF EXISTS {raw}")
    # Auto-detection off, every option pinned: a short row raises instead of re-sniffing the
    # delimiter, and a leading '#' is data, not a comment.
    try:
        con.execute(
            f"CREATE TABLE {raw} AS SELECT * FROM read_csv(?, header = true, "  # noqa: S608
            f"auto_detect = false, columns = {{{types}}}, delim = ',', quote = '\"', "
            "escape = '\"', comment = '', skip = 0, strict_mode = true, null_padding = false, "
            "ignore_errors = false)",
            [str(src)],
        )
    except duckdb.Error as error:
        raise BadGtfsValue(f"{table}: malformed CSV: {str(error)[:300]}") from error
    select, checks = [], []
    for c in columns:
        kind = spec.typed.get(c)
        q = f'"{c}"'
        if kind == "time":
            expr = gtfs_seconds_sql(c)
            select += [q, f'{expr} AS "{c.removesuffix("_time")}_s"']
            checks.append((c, expr))
        elif kind is not None:
            expr = typed_sql(c, kind)
            select.append(f"{expr} AS {q}")
            checks.append((c, expr))
        else:
            select.append(q)
    for c, kind in spec.typed.items():  # optional typed columns this version lacks
        if c not in columns and kind != "time":
            select.append(f'CAST(NULL AS {_SQL_TYPE[kind]}) AS "{c}"')
    select.append(f"'{version}' AS schedule_version")
    _check(con, table, raw, checks)
    written = con.execute(
        f"COPY (SELECT {', '.join(select)} FROM {raw}) TO ? (FORMAT parquet)",  # noqa: S608
        [str(out)],
    ).fetchall()[0][0]
    count = int(con.execute(f"SELECT count(*) FROM {raw}").fetchall()[0][0])  # noqa: S608
    con.execute(f"DROP TABLE {raw}")
    if int(written) != count:  # pragma: no cover - COPY has no filter; a guard, not a branch
        raise BadGtfsValue(f"{table}: wrote {written} rows of {count}")
    return count


def typed_sql(column: str, kind: str) -> str:
    """SQL for a typed column: NULL unless the text matches an exact pattern."""
    v = f"nullif({trim_sql(column)}, '')"
    if kind == "int":
        return f"CASE WHEN regexp_full_match({v}, '-?[0-9]{{1,9}}') THEN CAST({v} AS INTEGER) END"
    if kind in ("lat", "lon"):
        limit = 90 if kind == "lat" else 180
        number = f"CAST({v} AS DOUBLE)"
        return (
            f"CASE WHEN regexp_full_match({v}, '-?[0-9]{{1,3}}(\\.[0-9]+)?') "
            f"AND abs({number}) <= {limit} THEN {number} END"
        )
    if kind == "date":
        parsed = f"CAST(try_strptime({v}, '%Y%m%d') AS DATE)"
        return f"CASE WHEN regexp_full_match({v}, '[1-9][0-9]{{7}}') THEN {parsed} END"
    raise ValueError(f"unknown kind {kind!r}")  # pragma: no cover - TABLES is a constant


def _check(
    con: duckdb.DuckDBPyConnection, table: str, raw: str, checks: list[tuple[str, str]]
) -> None:
    """One scan: refuse the version if any non-blank value failed to parse; name an example."""
    if not checks:  # pragma: no cover - every table has at least one typed column
        return
    parts = []
    for c, expr in checks:
        bad = f"nullif({trim_sql(c)}, '') IS NOT NULL AND ({expr}) IS NULL"
        parts += [f"count_if({bad})", f'min("{c}") FILTER (WHERE {bad})']
    result = con.execute(f"SELECT {', '.join(parts)} FROM {raw}").fetchall()[0]  # noqa: S608
    for i, (c, _) in enumerate(checks):
        n, example = result[2 * i], result[2 * i + 1]
        if n:
            raise BadGtfsValue(f"{table}.{c}: {n} value(s) didn't parse, e.g. {example!r}")


@dataclass
class LoadResult:
    lines: list[str]
    failed: dict[str, str]  # version_id -> error


def load_gtfs(bucket: Bucket, workdir: Path | None = None, *, force: bool = False) -> LoadResult:
    """Rebuild `dim_schedule_version`, then extract every version not yet extracted.

    Superseded versions are extracted too: rows matched against them must still resolve.
    One refused version doesn't stop the others; failures are returned for the caller to
    report and exit non-zero on.
    """
    from ghostbus_decode.gtfs_versions import report, write_dim

    build = write_dim(bucket)
    result = LoadResult([report(build)], {})
    for v in build.versions:
        try:
            marker = extract_version(
                bucket, v.version_id, build.zip_keys[v.version_id], workdir, force=force
            )
        except (BadGtfsValue, MissingTable) as error:
            result.failed[v.version_id] = str(error)
            result.lines.append(f"  {v.version_id}: REFUSED: {error}")
            continue
        if marker is None:
            result.lines.append(f"  {v.version_id}: already extracted")
        else:
            rows = cast("dict[str, int]", marker["rows"])
            counts = ", ".join(f"{t} {n:,}" for t, n in sorted(rows.items()))
            result.lines.append(f"  {v.version_id}: extracted {counts}")
    return result


def main() -> None:  # pragma: no cover - thin CLI over tested functions
    """uv run python -m ghostbus_decode.gtfs_tables --bucket <data bucket> [--force]"""
    import argparse
    import sys

    import boto3

    from ghostbus_decode.s3 import S3Bucket

    parser = argparse.ArgumentParser(description="Load GTFS versions from bronze into derived/.")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--force", action="store_true", help="re-extract every version")
    args = parser.parse_args()
    bucket = S3Bucket(boto3.client("s3", region_name="us-west-2"), args.bucket)
    result = load_gtfs(bucket, force=args.force)
    print("\n".join(result.lines))
    if result.failed:
        sys.exit(f"{len(result.failed)} version(s) refused")


if __name__ == "__main__":  # pragma: no cover
    main()
