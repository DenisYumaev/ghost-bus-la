"""Tests for syncing marker-listed derived data to a local folder for dbt."""

import json
from datetime import date
from pathlib import Path

from ghostbus_decode.sync import sync, utc_days_for


class FakeBucket:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(k for k in self.objects if k.startswith(prefix))

    def get(self, key: str) -> bytes:
        return self.objects[key]


def marker(parts: dict[str, list[str]]) -> bytes:
    return json.dumps({"part_keys": parts, "run": "r1"}).encode()


VP_DAY = "derived/decoded/vehicle_position/dt=2026-11-14/"
VP_PART = VP_DAY + "run=r1/part-0-0.parquet"
STALE = VP_DAY + "run=r0/part-0-0.parquet"  # an older run not in the marker
LOG = "bronze/_fetch_log/dt=2026-11-14/hour=05/abcd.jsonl"


def bucket() -> FakeBucket:
    return FakeBucket({
        VP_PART: b"vp parquet", STALE: b"stale",
        VP_DAY + "_SUCCESS": marker({"vehicle_position": [VP_PART], "schema_fingerprint": [],
                                     "quarantine": []}),
        LOG: b'{"event": "fetch"}\n',
    })  # fmt: skip


def test_a_service_date_needs_its_utc_day_and_the_next() -> None:
    # Service date D runs from about 03:00 LA on D to past 01:00 LA on D+1, which ends on
    # UTC day D+1; the observation window adds an hour after the last scheduled end.
    assert utc_days_for(date(2026, 11, 14), date(2026, 11, 15)) == [
        date(2026, 11, 14), date(2026, 11, 15), date(2026, 11, 16),
    ]  # fmt: skip


def test_copies_only_marker_listed_parts(tmp_path: Path) -> None:
    report = sync(bucket(), date(2026, 11, 14), date(2026, 11, 14), tmp_path)
    copied = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.parquet"))
    assert copied == ["decoded/vehicle_position/dt=2026-11-14/part-0-0.parquet"]
    assert (tmp_path / "decoded/vehicle_position/dt=2026-11-14/part-0-0.parquet").read_bytes() == (
        b"vp parquet"
    )
    assert report["missing"]["trip_update"] == ["2026-11-14", "2026-11-15"]
    assert report["missing"]["vehicle_position"] == ["2026-11-15"]


def test_copies_the_fetch_log_hours(tmp_path: Path) -> None:
    sync(bucket(), date(2026, 11, 14), date(2026, 11, 14), tmp_path)
    [log] = (tmp_path / "fetch_log/dt=2026-11-14").iterdir()
    assert log.read_bytes() == b'{"event": "fetch"}\n'
    assert log.name == "hour=05-abcd.jsonl"


def test_a_resync_replaces_a_day_wholesale(tmp_path: Path) -> None:
    day_dir = tmp_path / "decoded/vehicle_position/dt=2026-11-14"
    day_dir.mkdir(parents=True)
    (day_dir / "part-9-9.parquet").write_bytes(b"left over from an older run")
    sync(bucket(), date(2026, 11, 14), date(2026, 11, 14), tmp_path)
    assert sorted(p.name for p in day_dir.iterdir()) == ["part-0-0.parquet"]


def test_gtfs_versions_with_a_current_success_marker_are_copied(tmp_path: Path) -> None:
    from ghostbus_decode.gtfs_tables import EXTRACTOR_VERSION

    good, old = "a" * 16, "b" * 16
    b = bucket()
    b.objects.update({
        "derived/decoded/gtfs/dim_schedule_version.parquet": b"dim",
        f"derived/decoded/gtfs/{good}/trips.parquet": b"trips",
        f"derived/decoded/gtfs/{good}/_SUCCESS":
            json.dumps({"extractor_version": EXTRACTOR_VERSION}).encode(),
        f"derived/decoded/gtfs/{old}/trips.parquet": b"old trips",
        f"derived/decoded/gtfs/{old}/_SUCCESS": json.dumps({"extractor_version": 0}).encode(),
    })  # fmt: skip
    report = sync(b, date(2026, 11, 14), date(2026, 11, 14), tmp_path)
    assert (tmp_path / "gtfs/dim_schedule_version.parquet").read_bytes() == b"dim"
    assert (tmp_path / f"gtfs/{good}/trips.parquet").read_bytes() == b"trips"
    assert not (tmp_path / f"gtfs/{old}").exists()
    assert report["gtfs_versions"] == [good]
    assert report["gtfs_not_extracted"] == [old]
