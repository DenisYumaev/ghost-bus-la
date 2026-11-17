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
    EXTRACTOR_VERSION,
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
        self.deleted: list[str] = []

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(k for k in self.objects if k.startswith(prefix))

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def put(self, key: str, body: bytes) -> None:
        self.puts.append(key)
        self.objects[key] = body

    def delete(self, key: str) -> None:
        self.deleted.append(key)
        del self.objects[key]


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
    assert first.failed == {}
    assert any("extracted" in line and "stop_times 4" in line for line in first.lines)
    again = load_gtfs(bucket, tmp_path)
    assert any("already extracted" in line for line in again.lines)


# --- strictness: DuckDB's own casts and CSV sniffer are too lenient (checked on 2.0.0) -------


def refused(tmp_path: Path, table: str, text: str, match: str) -> None:
    bucket = FakeBucket({ZIP_KEY: make_zip({**FILES, f"{table}.txt": text})})
    with pytest.raises(BadGtfsValue, match=match):
        extract_version(bucket, VERSION, ZIP_KEY, workdir=tmp_path)
    assert version_prefix(VERSION) + SUCCESS not in bucket.objects


@pytest.mark.parametrize("value", ["2.5", "1e2", "1_0", "0x10", "+3", "3000000000"])
def test_a_non_integer_stop_sequence_is_refused_not_rounded(tmp_path: Path, value: str) -> None:
    # DuckDB's TRY_CAST turns '2.5' into 3 and '1e2' into 100.
    row = f"T2-JUNE26,09:00:00,09:00:00,2083,{value},,0,0,E2,10,,1,\n"
    refused(tmp_path, "stop_times", STOP_TIMES + row, r"stop_times\.stop_sequence")


@pytest.mark.parametrize("lat", ["NaN", "inf", "91", "1e1", "33.97.1"])
def test_an_impossible_coordinate_is_refused(tmp_path: Path, lat: str) -> None:
    stops = STOPS + f"2,2,Somewhere,,{lat},-118.1,,,,\n"
    refused(tmp_path, "stops", stops, r"stops\.stop_lat")


@pytest.mark.parametrize("day", ["20260230", "20261301", "00000101", "2026070"])
def test_an_impossible_date_is_refused(tmp_path: Path, day: str) -> None:
    refused(tmp_path, "calendar_dates", f"service_id,date,exception_type\nX,{day},1\n",
            r"calendar_dates\.date")  # fmt: skip


def test_a_short_row_is_refused_not_resniffed(tmp_path: Path) -> None:
    # With auto-detection, DuckDB re-sniffs and reads the file as one column.
    refused(tmp_path, "calendar_dates", "service_id,date,exception_type\nX,20260704\n",
            "malformed CSV")  # fmt: skip


def test_a_leading_hash_is_data_not_a_comment(tmp_path: Path) -> None:
    routes = ROUTES + "#99-13201,99,Metro Local Line,,3,,,\n"
    bucket = FakeBucket({ZIP_KEY: make_zip({**FILES, "routes.txt": routes})})
    extract_version(bucket, VERSION, ZIP_KEY, workdir=tmp_path)
    ids = query(bucket, "routes", "SELECT route_id FROM routes", tmp_path)
    assert ("#99-13201",) in ids


def test_quoted_commas_and_newlines_survive(tmp_path: Path) -> None:
    stops = STOPS + '2,2,"Main, 1st\nNorth side",,34.0,-118.2,,,,\n'
    bucket = FakeBucket({ZIP_KEY: make_zip({**FILES, "stops.txt": stops})})
    extract_version(bucket, VERSION, ZIP_KEY, workdir=tmp_path)
    names = query(bucket, "stops", "SELECT stop_name FROM stops ORDER BY stop_id", tmp_path)
    assert names == [("Paramount / Slauson",), ("Main, 1st\nNorth side",)]


def test_a_duplicate_header_is_refused(tmp_path: Path) -> None:
    text = "service_id,date,date,exception_type\nX,20260704,20260704,1\n"
    refused(tmp_path, "calendar_dates", text, "duplicate column")


def test_a_column_clashing_with_a_generated_one_is_refused(tmp_path: Path) -> None:
    refused(tmp_path, "routes", "route_id,route_short_name,route_type,schedule_version\n1,1,3,x\n",
            "clashes")  # fmt: skip


def test_a_missing_required_column_is_refused(tmp_path: Path) -> None:
    no_departure = "trip_id,arrival_time,stop_id,stop_sequence\nT1-JUNE26,08:50:00,2079,1\n"
    refused(tmp_path, "stop_times", no_departure, "missing required column 'departure_time'")


def test_an_optional_typed_column_that_is_absent_becomes_a_typed_null(tmp_path: Path) -> None:
    lean = (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        "T1-JUNE26,08:50:00,08:50:00,2079,1\n"
    )
    bucket = FakeBucket({ZIP_KEY: make_zip({**FILES, "stop_times.txt": lean})})
    extract_version(bucket, VERSION, ZIP_KEY, workdir=tmp_path)
    assert query(bucket, "stop_times", "SELECT timepoint, typeof(timepoint) FROM stop_times",
                 tmp_path) == [(None, "INTEGER")]  # fmt: skip


def test_tabs_and_carriage_returns_around_values_are_trimmed(tmp_path: Path) -> None:
    dates = "service_id,date,exception_type\r\nX,\t20260704\t,1\r\n"
    bucket = FakeBucket({ZIP_KEY: make_zip({**FILES, "calendar_dates.txt": dates})})
    extract_version(bucket, VERSION, ZIP_KEY, workdir=tmp_path)
    assert query(bucket, "calendar_dates", "SELECT date FROM calendar_dates", tmp_path) == [
        (date(2026, 7, 4),)
    ]


# --- versions, markers, failures -------------------------------------------------------------


def test_a_marker_from_an_older_extractor_is_redone(loaded: FakeBucket, tmp_path: Path) -> None:
    key = version_prefix(VERSION) + SUCCESS
    loaded.objects[key] = json.dumps({"extractor_version": 1}).encode()
    assert extract_version(loaded, VERSION, ZIP_KEY, workdir=tmp_path) is not None
    assert json.loads(loaded.objects[key])["extractor_version"] == EXTRACTOR_VERSION


def test_an_unreadable_marker_is_redone(loaded: FakeBucket, tmp_path: Path) -> None:
    loaded.objects[version_prefix(VERSION) + SUCCESS] = b"not json"
    assert extract_version(loaded, VERSION, ZIP_KEY, workdir=tmp_path) is not None


def test_force_redoes_a_complete_version(loaded: FakeBucket, tmp_path: Path) -> None:
    assert extract_version(loaded, VERSION, ZIP_KEY, workdir=tmp_path, force=True) is not None


def test_one_refused_version_doesnt_stop_the_others(tmp_path: Path) -> None:
    good_sha = VERSION + "1619365ea0626262bc3d93d5e6bdd0df03288cd6120f6058"
    bad_sha = "d" * 64
    good_key, bad_key = ZIP_KEY, f"bronze/gtfs_static/dt=2026-11-16/{bad_sha[:16]}.zip"
    bad_zip = make_zip(
        {**FILES, "stop_times.txt": STOP_TIMES + "T9,7:61:00,7:61:00,1,1,,0,0,E,1,,1,\n"}
    )

    def written(sha: str, key: str, at: str) -> str:
        rec = {"event": "fetch", "feed": "gtfs_static", "fetched_at": at,
               "outcome": "written", "content_hash": sha, "object_key": key}  # fmt: skip
        return json.dumps(rec)

    bucket = FakeBucket({
        good_key: make_zip(FILES), bad_key: bad_zip,
        "bronze/_fetch_log/dt=2026-11-15/hour=15/a.jsonl":
            (written(good_sha, good_key, "2026-11-15T15:13:04Z") + "\n").encode(),
        "bronze/_fetch_log/dt=2026-11-16/hour=11/b.jsonl":
            (written(bad_sha, bad_key, "2026-11-16T11:00:00Z") + "\n").encode(),
    })  # fmt: skip
    result = load_gtfs(bucket, tmp_path)
    assert list(result.failed) == [bad_sha[:16]]
    assert version_prefix(VERSION) + SUCCESS in bucket.objects  # the good one still loaded
    assert any("REFUSED" in line for line in result.lines)
    # The refused version gets no date range: the good one stays in force past Nov 16.
    from ghostbus_decode.gtfs_versions import DIM_KEY

    dim = tmp_path / "dim.parquet"
    dim.write_bytes(bucket.objects[DIM_KEY])
    with duckdb.connect() as con:
        in_dim = con.execute("SELECT version_id, valid_to FROM read_parquet(?)", [str(dim)])
        assert in_dim.fetchall() == [(VERSION, None)]


def test_optional_text_columns_a_version_lacks_become_nulls(tmp_path: Path) -> None:
    lean = "stop_id,stop_name,stop_lat,stop_lon\n1,Paramount / Slauson,33.97,-118.11\n"
    bucket = FakeBucket({ZIP_KEY: make_zip({**FILES, "stops.txt": lean})})
    extract_version(bucket, VERSION, ZIP_KEY, workdir=tmp_path)
    got = query(bucket, "stops", "SELECT stop_code, parent_station, typeof(parent_station) "
                "FROM stops", tmp_path)  # fmt: skip
    assert got == [(None, None, "VARCHAR")]


def test_frequency_based_trips_refuse_the_version(tmp_path: Path) -> None:
    freq = "trip_id,start_time,end_time,headway_secs\nT1-JUNE26,06:00:00,09:00:00,600\n"
    bucket = FakeBucket({ZIP_KEY: make_zip({**FILES, "frequencies.txt": freq})})
    with pytest.raises(BadGtfsValue, match="frequencies"):
        extract_version(bucket, VERSION, ZIP_KEY, workdir=tmp_path)


def test_an_empty_frequencies_file_is_fine(tmp_path: Path) -> None:
    bucket = FakeBucket({ZIP_KEY: make_zip({**FILES, "frequencies.txt": "trip_id,start_time\n"})})
    assert extract_version(bucket, VERSION, ZIP_KEY, workdir=tmp_path) is not None
