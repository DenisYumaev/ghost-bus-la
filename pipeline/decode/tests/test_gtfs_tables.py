"""Tests for extracting one schedule version's tables to typed Parquet (pipeline spec, section 4).

The fixture ZIP copies the headers of Metro's real files (2026-11-15 version) and the quirks
the day-1 probe found.
"""

import io
import json
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pytest
from ghostbus_decode.gtfs_tables import (
    SUCCESS,
    BadGtfsValue,
    MissingTable,
    extract_version,
    load_gtfs,
    version_prefix,
)

VERSION = "cb1a2283abecc0af"
ZIP_KEY = f"bronze/gtfs_static/dt=2026-11-15/{VERSION}.zip"

ROUTES = (
    "route_id,route_short_name,route_long_name,route_desc,route_type,route_color,"
    "route_text_color,route_url\n"
    '2-13201,2,Metro Local Line,"WESTWOOD - EXPOSITION PARK VIA SUNSET-ALVARADO",3,,,\n'
    "10-13201,10/48,Metro Local Line,,3,,,\n"
    '854-13201,"Dodger Stadium Express",,,3,,,\n'
)
TRIPS = (
    "route_id,service_id,trip_id,trip_headsign,direction_id,block_id,shape_id,trip_id_event\n"
    "2-13201,JUNE26-D05CAR-3_Sunday,T1-JUNE26,,1,2065100,S1,E1\n"
    "10-13201,JUNE26-D05CAR-3_Sunday,T2-JUNE26,,0,,S2,E2\n"  # no block_id (713 real trips)
)
STOP_TIMES = (
    "﻿trip_id,arrival_time,departure_time,stop_id,stop_sequence,stop_headsign,pickup_type,"
    "drop_off_type,trip_id_event,route_code,destination_code,timepoint,bay_num\n"
    "T1-JUNE26,08:50:00,08:50:00,2079,1,206 - Vermont / Athens Station,0,0,E1,206,"
    "Vermont / Athens Station,1,\n"
    "T1-JUNE26,8:55:30,8:55:30,2080,2,,0,0,E1,206,,0,\n"  # hour without a leading zero
    "T1-JUNE26,,,2081,3,,0,0,E1,206,,0,\n"  # blank between timepoints
    "T2-JUNE26,29:45:00,29:45:00,2082,1,,0,0,E2,10,,1,\n"  # Metro's latest time
)
STOPS = (
    "stop_id,stop_code,stop_name,stop_desc,stop_lat,stop_lon,stop_url,location_type,"
    "parent_station,tpis_name\n"
    "1,1,Paramount / Slauson,,  33.973248,-118.113113,,,,\n"
)
CALENDAR = (
    "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
    "JUNE26-D05CAR-3_Sunday,0,0,0,0,0,0,1,20260607,20261206\n"
)
CALENDAR_DATES = "service_id,date,exception_type\nJUNE26-D05CAR-3_Sunday,20260704,1\n"
FEED_INFO = (
    "feed_id,feed_publisher_name,feed_publisher_url,feed_lang,feed_version,feed_license,"
    "feed_contact_email,feed_contact_url,feed_start_date,feed_end_date\n"
    'us_ca_lacmta_bus,"Los Angeles County Metropolitan Transportation Authority",'
    "https://www.metro.net,en,,,,https://developer.metro.net,20260607,20261212\n"
)
FILES = {
    "routes.txt": ROUTES, "trips.txt": TRIPS, "stop_times.txt": STOP_TIMES,
    "stops.txt": STOPS, "calendar.txt": CALENDAR, "calendar_dates.txt": CALENDAR_DATES,
    "feed_info.txt": FEED_INFO, "shapes.txt": "shape_id\nS1\n",
}  # fmt: skip


def make_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buf.getvalue()


class FakeBucket:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.puts: list[str] = []

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(k for k in self.objects if k.startswith(prefix))

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def put(self, key: str, body: bytes) -> None:
        self.puts.append(key)
        self.objects[key] = body


def query(bucket: FakeBucket, table: str, sql: str, tmp_path: Path) -> list[tuple[Any, ...]]:
    path = tmp_path / f"{table}.parquet"
    path.write_bytes(bucket.objects[f"{version_prefix(VERSION)}{table}.parquet"])
    with duckdb.connect() as con:
        con.execute(f"CREATE VIEW {table} AS SELECT * FROM read_parquet('{path}')")  # noqa: S608
        return con.execute(sql).fetchall()


@pytest.fixture
def loaded(tmp_path: Path) -> FakeBucket:
    bucket = FakeBucket({ZIP_KEY: make_zip(FILES)})
    extract_version(bucket, VERSION, ZIP_KEY, workdir=tmp_path)
    return bucket


def test_writes_each_table_then_success_last(loaded: FakeBucket) -> None:
    prefix = version_prefix(VERSION)
    assert loaded.puts[-1] == prefix + SUCCESS
    assert sorted(loaded.puts[:-1]) == sorted(
        f"{prefix}{t}.parquet"
        for t in ["routes", "trips", "stop_times", "stops", "calendar", "calendar_dates",
                  "feed_info"]
    )  # fmt: skip
    counts = json.loads(loaded.objects[prefix + SUCCESS])
    assert counts["rows"]["stop_times"] == 4
    assert counts["schedule_version"] == VERSION


def test_shapes_are_not_extracted(loaded: FakeBucket) -> None:
    assert not any("shapes" in k for k in loaded.puts)


def test_times_parse_to_seconds_and_keep_their_text(loaded: FakeBucket, tmp_path: Path) -> None:
    rows = query(loaded, "stop_times",
                 "SELECT stop_sequence, arrival_time, arrival_s, departure_s FROM stop_times "
                 "ORDER BY trip_id, stop_sequence", tmp_path)  # fmt: skip
    assert rows == [
        (1, "08:50:00", 31800, 31800),
        (2, "8:55:30", 32130, 32130),
        (3, None, None, None),
        (1, "29:45:00", 107100, 107100),
    ]


def test_stop_sequence_sorts_as_a_number(tmp_path: Path) -> None:
    extra = STOP_TIMES + "T1-JUNE26,09:10:00,09:10:00,2090,10,,0,0,E1,206,,1,\n"
    bucket = FakeBucket({ZIP_KEY: make_zip({**FILES, "stop_times.txt": extra})})
    extract_version(bucket, VERSION, ZIP_KEY, workdir=tmp_path)
    seqs = query(bucket, "stop_times", "SELECT stop_sequence FROM stop_times "
                 "WHERE trip_id = 'T1-JUNE26' ORDER BY stop_sequence", tmp_path)  # fmt: skip
    assert [s for (s,) in seqs] == [1, 2, 3, 10]


def test_identifiers_stay_text(loaded: FakeBucket, tmp_path: Path) -> None:
    rows = query(
        loaded, "routes", "SELECT route_short_name FROM routes ORDER BY route_id", tmp_path
    )
    assert [r for (r,) in rows] == ["10/48", "2", "Dodger Stadium Express"]
    blocks = query(loaded, "trips", "SELECT block_id, trip_headsign, direction_id FROM trips "
                   "ORDER BY trip_id", tmp_path)  # fmt: skip
    assert blocks == [("2065100", None, 1), (None, None, 0)]


def test_typed_dates_and_coordinates(loaded: FakeBucket, tmp_path: Path) -> None:
    assert query(loaded, "calendar", "SELECT sunday, start_date, end_date FROM calendar",
                 tmp_path) == [(1, date(2026, 6, 7), date(2026, 12, 6))]  # fmt: skip
    assert query(loaded, "calendar_dates", "SELECT date, exception_type FROM calendar_dates",
                 tmp_path) == [(date(2026, 7, 4), 1)]  # fmt: skip
    assert query(loaded, "stops", "SELECT stop_lat, stop_lon FROM stops", tmp_path) == [
        (33.973248, -118.113113)
    ]


def test_every_row_carries_its_version(loaded: FakeBucket, tmp_path: Path) -> None:
    assert query(loaded, "trips", "SELECT DISTINCT schedule_version FROM trips", tmp_path) == [
        (VERSION,)
    ]


def test_an_extracted_version_is_skipped(loaded: FakeBucket, tmp_path: Path) -> None:
    before = list(loaded.puts)
    assert extract_version(loaded, VERSION, ZIP_KEY, workdir=tmp_path) is None
    assert loaded.puts == before


def test_a_crash_before_success_is_redone_on_the_next_run(tmp_path: Path) -> None:
    bucket = FakeBucket({ZIP_KEY: make_zip(FILES)})
    bucket.objects[f"{version_prefix(VERSION)}routes.parquet"] = b"half-written leftover"
    extract_version(bucket, VERSION, ZIP_KEY, workdir=tmp_path)
    assert bucket.objects[f"{version_prefix(VERSION)}routes.parquet"] != b"half-written leftover"
    assert version_prefix(VERSION) + SUCCESS in bucket.objects


def test_a_malformed_time_refuses_the_version_and_writes_no_success(tmp_path: Path) -> None:
    bad = STOP_TIMES + "T2-JUNE26,7:61:00,7:61:00,2083,2,,0,0,E2,10,,1,\n"
    bucket = FakeBucket({ZIP_KEY: make_zip({**FILES, "stop_times.txt": bad})})
    with pytest.raises(BadGtfsValue, match=r"stop_times\.arrival_time.*7:61:00"):
        extract_version(bucket, VERSION, ZIP_KEY, workdir=tmp_path)
    assert version_prefix(VERSION) + SUCCESS not in bucket.objects


def test_a_malformed_date_refuses_the_version(tmp_path: Path) -> None:
    bad = "service_id,date,exception_type\nX,2026-07-04,1\n"
    bucket = FakeBucket({ZIP_KEY: make_zip({**FILES, "calendar_dates.txt": bad})})
    with pytest.raises(BadGtfsValue, match=r"calendar_dates\.date"):
        extract_version(bucket, VERSION, ZIP_KEY, workdir=tmp_path)


def test_a_missing_required_table_refuses_the_version(tmp_path: Path) -> None:
    files = {k: v for k, v in FILES.items() if k != "trips.txt"}
    bucket = FakeBucket({ZIP_KEY: make_zip(files)})
    with pytest.raises(MissingTable, match=r"trips\.txt"):
        extract_version(bucket, VERSION, ZIP_KEY, workdir=tmp_path)


def test_optional_tables_may_be_absent(tmp_path: Path) -> None:
    files = {k: v for k, v in FILES.items() if k not in ("calendar.txt", "feed_info.txt")}
    bucket = FakeBucket({ZIP_KEY: make_zip(files)})
    extract_version(bucket, VERSION, ZIP_KEY, workdir=tmp_path)
    assert not any(k.endswith(("calendar.parquet", "feed_info.parquet")) for k in bucket.puts)


def test_rejects_a_version_id_that_could_escape_its_prefix(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="version id"):
        extract_version(FakeBucket({}), "../bronze", ZIP_KEY, workdir=tmp_path)


def test_a_version_needs_calendar_or_calendar_dates(tmp_path: Path) -> None:
    files = {k: v for k, v in FILES.items() if k not in ("calendar.txt", "calendar_dates.txt")}
    bucket = FakeBucket({ZIP_KEY: make_zip(files)})
    with pytest.raises(MissingTable, match="calendar"):
        extract_version(bucket, VERSION, ZIP_KEY, workdir=tmp_path)


def test_a_column_name_that_isnt_an_identifier_refuses_the_version(tmp_path: Path) -> None:
    # Column names go into SQL, so anything but a plain identifier is refused.
    bad = 'route_id,"route; DROP"\n1,x\n'
    bucket = FakeBucket({ZIP_KEY: make_zip({**FILES, "routes.txt": bad})})
    with pytest.raises(BadGtfsValue, match="unexpected column name"):
        extract_version(bucket, VERSION, ZIP_KEY, workdir=tmp_path)


def test_temp_files_are_removed(loaded: FakeBucket, tmp_path: Path) -> None:
    assert not any(p.suffix in (".txt", ".zip") for p in tmp_path.rglob("*"))


def test_load_gtfs_builds_the_dimension_then_extracts_each_version_once(tmp_path: Path) -> None:
    from ghostbus_decode.gtfs_versions import DIM_KEY

    sha = VERSION + "1619365ea0626262bc3d93d5e6bdd0df03288cd6120f6058"
    written = json.dumps(
        {"event": "fetch", "feed": "gtfs_static", "fetched_at": "2026-11-15T15:13:04.305Z",
         "outcome": "written", "content_hash": sha, "object_key": ZIP_KEY}
    )  # fmt: skip
    bucket = FakeBucket(
        {ZIP_KEY: make_zip(FILES),
         "bronze/_fetch_log/dt=2026-11-15/hour=15/a.jsonl": (written + "\n").encode()}
    )  # fmt: skip
    first = load_gtfs(bucket, tmp_path)
    assert DIM_KEY in bucket.objects
    assert any("extracted" in line and "stop_times 4" in line for line in first)
    again = load_gtfs(bucket, tmp_path)
    assert any("already extracted" in line for line in again)
