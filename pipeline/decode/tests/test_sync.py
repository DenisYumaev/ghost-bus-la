"""Tests for syncing marker-listed derived data to a local folder for dbt."""

import json
from datetime import date
from pathlib import Path

import pytest
from ghostbus_decode.decode import DECODER_VERSION
from ghostbus_decode.gtfs_tables import EXTRACTOR_VERSION
from ghostbus_decode.sync import IncompleteRange, sync, utc_days_for

DAYS = ("2026-11-13", "2026-11-14", "2026-11-15")
V_GOOD, V_OLD = "a" * 16, "b" * 16


class FakeBucket:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.fail_on: str | None = None

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(k for k in self.objects if k.startswith(prefix))

    def get(self, key: str) -> bytes:
        if self.fail_on and self.fail_on in key:
            raise ConnectionError(key)
        return self.objects[key]


def decoded_day(day: str, table: str) -> dict[str, bytes]:
    prefix = f"derived/decoded/{table}/dt={day}/"
    part = prefix + "run=r1/part-0-0.parquet"
    marker = {
        "part_keys": {table: [part], "schema_fingerprint": [], "quarantine": []},
        "decoder_version": DECODER_VERSION,
    }
    return {part: f"{table} {day}".encode(), prefix + "run=r0/part-0-0.parquet": b"stale",
            prefix + "_SUCCESS": json.dumps(marker).encode()}  # fmt: skip


def bucket(days: tuple[str, ...] = DAYS) -> FakeBucket:
    objects: dict[str, bytes] = {}
    for day in days:
        objects |= decoded_day(day, "vehicle_position") | decoded_day(day, "trip_update")
        objects[f"bronze/_fetch_log/dt={day}/hour=05/abcd.jsonl"] = b'{"event": "fetch"}\n'
    objects |= {
        "derived/decoded/gtfs/dim_schedule_version.parquet": b"dim",
        f"derived/decoded/gtfs/{V_GOOD}/trips.parquet": b"trips",
        f"derived/decoded/gtfs/{V_GOOD}/shapes.parquet": b"not in the marker",
        f"derived/decoded/gtfs/{V_GOOD}/_SUCCESS": json.dumps(
            {"extractor_version": EXTRACTOR_VERSION, "rows": {"trips": 2}}).encode(),
        f"derived/decoded/gtfs/{V_OLD}/trips.parquet": b"old trips",
        f"derived/decoded/gtfs/{V_OLD}/_SUCCESS": json.dumps(
            {"extractor_version": 0, "rows": {"trips": 2}}).encode(),
    }  # fmt: skip
    return FakeBucket(objects)


ONE_DAY = (date(2026, 11, 14), date(2026, 11, 14))


def files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def test_a_service_date_needs_the_utc_days_around_it() -> None:
    # The previous UTC day for early cancellation notices; the next for trips past midnight LA.
    assert [d.isoformat() for d in utc_days_for(*ONE_DAY)] == list(DAYS)


def test_copies_exactly_the_marker_listed_files(tmp_path: Path) -> None:
    report = sync(bucket(), *ONE_DAY, tmp_path)
    assert files(tmp_path) == [
        "_sync.json",
        *[f"decoded/{t}/dt={d}/part-0-0.parquet" for t in ("trip_update", "vehicle_position")
          for d in DAYS],
        *[f"fetch_log/dt={d}/hour=05-abcd.jsonl" for d in DAYS],
        "gtfs/aaaaaaaaaaaaaaaa/trips.parquet",  # not shapes: the marker doesn't list it
        "gtfs/dim_schedule_version.parquet",
    ]  # fmt: skip
    assert report["gtfs_versions"] == [V_GOOD]
    assert report["gtfs_not_extracted"] == [V_OLD]
    assert json.loads((tmp_path / "_sync.json").read_text())["start"] == "2026-11-14"


def test_a_missing_decoded_day_fails_and_changes_nothing(tmp_path: Path) -> None:
    sync(bucket(), *ONE_DAY, tmp_path)
    before = files(tmp_path)
    with pytest.raises(IncompleteRange, match="2026-11-15"):
        sync(bucket(DAYS[:2]), *ONE_DAY, tmp_path)  # Nov 15 not decoded
    assert files(tmp_path) == before


def test_an_interrupted_sync_leaves_the_previous_copy_intact(tmp_path: Path) -> None:
    sync(bucket(), *ONE_DAY, tmp_path)
    before = {p: (tmp_path / p).read_bytes() for p in files(tmp_path)}
    broken = bucket()
    broken.fail_on = "dt=2026-11-15"
    with pytest.raises(ConnectionError):
        sync(broken, *ONE_DAY, tmp_path)
    assert {p: (tmp_path / p).read_bytes() for p in files(tmp_path)} == before


def test_nothing_outside_the_new_range_survives(tmp_path: Path) -> None:
    stale = tmp_path / "decoded/vehicle_position/dt=2026-10-01/part-0-0.parquet"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old day")
    old_version = tmp_path / "gtfs/cccccccccccccccc/trips.parquet"
    old_version.parent.mkdir(parents=True)
    old_version.write_bytes(b"refused or stale version")
    sync(bucket(), *ONE_DAY, tmp_path)
    assert not stale.exists()
    assert not old_version.exists()


def test_a_day_decoded_by_an_older_decoder_is_refused(tmp_path: Path) -> None:
    # Mixed decoder versions would mix column sets in one dbt glob.
    old = bucket()
    key = "derived/decoded/trip_update/dt=2026-11-15/_SUCCESS"
    marker = json.loads(old.objects[key])
    marker["decoder_version"] = DECODER_VERSION - 1
    old.objects[key] = json.dumps(marker).encode()
    with pytest.raises(IncompleteRange, match="older decoder"):
        sync(old, *ONE_DAY, tmp_path)
