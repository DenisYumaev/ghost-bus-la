"""Tests for building `dim_schedule_version` from the ZIPs in bronze (pipeline spec, section 4)."""

import io
import json
import zipfile
from datetime import date
from pathlib import Path

import duckdb
import pytest
from ghostbus_decode.gtfs_sightings import GTFS_PREFIX
from ghostbus_decode.gtfs_versions import (
    DIM_KEY,
    build_versions,
    read_feed_dates,
    versions_parquet,
    write_dim,
)

# Metro's real feed_info.txt has one row and an empty feed_version (day-1 probe).
FEED_INFO = (
    "feed_publisher_name,feed_publisher_url,feed_lang,feed_start_date,feed_end_date,feed_version\n"
    "LACMTA,https://www.metro.net,en,20260607,20261212,\n"
)


def make_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buf.getvalue()


# --- feed dates ----------------------------------------------------------------------------


def test_reads_metros_feed_dates() -> None:
    assert read_feed_dates(make_zip({"feed_info.txt": FEED_INFO})) == (
        date(2026, 6, 7),
        date(2026, 12, 12),
    )


def test_tolerates_a_byte_order_mark_and_quoting() -> None:
    text = '﻿"feed_start_date","feed_end_date"\r\n"20260607","20261212"\r\n'
    assert read_feed_dates(make_zip({"feed_info.txt": text})) == (
        date(2026, 6, 7),
        date(2026, 12, 12),
    )


def test_missing_feed_info_or_empty_dates_give_none() -> None:
    assert read_feed_dates(make_zip({"routes.txt": "route_id\n1\n"})) == (None, None)
    empty = "feed_publisher_name,feed_start_date,feed_end_date\nLACMTA,,\n"
    assert read_feed_dates(make_zip({"feed_info.txt": empty})) == (None, None)


def test_more_than_one_feed_info_row_is_rejected() -> None:
    two = "feed_start_date,feed_end_date\n20260607,20261212\n20261213,20270601\n"
    with pytest.raises(ValueError, match="one row"):
        read_feed_dates(make_zip({"feed_info.txt": two}))


def test_a_malformed_date_is_rejected() -> None:
    bad = "feed_start_date,feed_end_date\n2026-06-07,20261212\n"
    with pytest.raises(ValueError, match="service date"):
        read_feed_dates(make_zip({"feed_info.txt": bad}))


# --- building and writing the dimension ----------------------------------------------------

SHA = "cb1a2283abecc0af1619365ea0626262bc3d93d5e6bdd0df03288cd6120f6058"
KEY = f"{GTFS_PREFIX}dt=2026-11-15/{SHA[:16]}.zip"
TODAY = date(2026, 11, 25)
LOG = "bronze/_fetch_log/dt=2026-11-15/hour=15/aaaa.jsonl"
WRITTEN = json.dumps(
    {"event": "fetch", "feed": "gtfs_static", "fetched_at": "2026-11-15T15:13:04.305Z",
     "outcome": "written", "content_hash": SHA, "object_key": KEY}
)  # fmt: skip


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


def bucket_with_metros_zip() -> FakeBucket:
    return FakeBucket({KEY: make_zip({"feed_info.txt": FEED_INFO}), LOG: (WRITTEN + "\n").encode()})


def test_builds_one_version_from_the_real_history() -> None:
    [v] = build_versions(bucket_with_metros_zip(), TODAY).versions
    assert (v.version_id, v.valid_from, v.valid_to) == (SHA[:16], date(2026, 11, 15), None)
    assert (v.feed_start_date, v.feed_end_date) == (date(2026, 6, 7), date(2026, 12, 12))


def read_parquet(body: bytes, tmp_path: Path) -> list[tuple[object, ...]]:
    path = tmp_path / "dim.parquet"
    path.write_bytes(body)
    with duckdb.connect() as con:
        return con.execute(
            # first_seen_at as UTC text: fetching TIMESTAMPTZ into Python would need pytz.
            "SELECT version_id, sha256, CAST(timezone('UTC', first_seen_at) AS VARCHAR), "
            "feed_start_date, feed_end_date, "
            "valid_from, valid_to, ever_in_force FROM read_parquet(?) ORDER BY valid_from",
            [str(path)],
        ).fetchall()


def test_parquet_has_one_typed_row_per_version(tmp_path: Path) -> None:
    rows = read_parquet(
        versions_parquet(build_versions(bucket_with_metros_zip(), TODAY).versions), tmp_path
    )
    [(vid, sha, seen_at, start, end, vfrom, vto, live)] = rows
    assert (vid, sha, start, end, vfrom, vto, live) == (
        SHA[:16], SHA, date(2026, 6, 7), date(2026, 12, 12), date(2026, 11, 15), None, True,
    )  # fmt: skip
    assert str(seen_at).startswith("2026-11-15 15:13:04.305")


def test_an_empty_dimension_still_has_its_columns(tmp_path: Path) -> None:
    assert read_parquet(versions_parquet([]), tmp_path) == []


def test_write_dim_overwrites_the_whole_file_and_is_idempotent(tmp_path: Path) -> None:
    bucket = bucket_with_metros_zip()
    write_dim(bucket, TODAY)
    first = bucket.objects[DIM_KEY]
    write_dim(bucket, TODAY)
    assert bucket.puts == [DIM_KEY, DIM_KEY]
    assert read_parquet(bucket.objects[DIM_KEY], tmp_path) == read_parquet(first, tmp_path)


def test_the_dimension_lives_under_derived() -> None:
    # The real guard against bronze writes is S3Bucket.put (tested in test_gtfs_sightings).
    assert DIM_KEY.startswith("derived/")


def test_parquet_orders_versions_and_marks_superseded_ones(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from ghostbus_core.schedule_versions import SeenZip, resolve_versions

    versions = resolve_versions(
        [SeenZip("a" * 64, datetime(2026, 11, 15, 16, tzinfo=UTC), None),
         SeenZip("b" * 64, datetime(2026, 11, 15, 22, tzinfo=UTC), None),
         SeenZip("c" * 64, datetime(2026, 11, 20, 16, tzinfo=UTC), None)]
    )  # fmt: skip
    rows = read_parquet(versions_parquet(versions), tmp_path)
    assert [(str(r[0])[0], r[5], r[6], r[7]) for r in rows] == [
        ("a", date(2026, 11, 15), date(2026, 11, 14), False),
        ("b", date(2026, 11, 15), date(2026, 11, 19), True),
        ("c", date(2026, 11, 20), None, True),
    ]


def test_a_header_only_feed_info_gives_none() -> None:
    assert read_feed_dates(make_zip({"feed_info.txt": "feed_start_date,feed_end_date\n"})) == (
        None,
        None,
    )


def test_main_prints_the_versions(capsys: pytest.CaptureFixture[str]) -> None:
    from ghostbus_decode.gtfs_versions import VersionBuild, report

    print(report(build_versions(bucket_with_metros_zip(), TODAY)))
    print(report(VersionBuild(build_versions(bucket_with_metros_zip(), TODAY).versions,
                              ["bronze/gtfs_static/dt=2026-11-25/x.zip"])))  # fmt: skip
    out = capsys.readouterr().out
    assert SHA[:16] in out
    assert "2026-11-15" in out
    assert "open" in out
    assert "waiting for its fetch-log hour" in out
