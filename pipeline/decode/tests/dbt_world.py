"""The dbt test world: a tiny bronze archive built by world.py, compacted, decoded, synced and
built with dbt. Shared by test_dbt.py and the publish integration tests, so it lives outside any
test module (importing a test module would collect its tests twice)."""

import json
import os
import shutil
from pathlib import Path
from typing import Any

from dbt.cli.main import dbtRunner
from world import build

DBT = Path(__file__).parents[3] / "pipeline" / "dbt"

VEHICLE = json.dumps({"id": "3912", "vehicle": {
    "trip": {"tripId": "T1-JUNE26", "startDate": "20261114", "startTime": "08:50:00",
             "routeId": "2-13201", "directionId": 1},
    "position": {"latitude": 34.06, "longitude": -118.30}, "timestamp": "1794675000",
    "currentStopSequence": 2,
    "vehicle": {"id": "3912"}}})  # fmt: skip
CANCELED = json.dumps({"id": "T2-JUNE26", "tripUpdate": {
    "trip": {"tripId": "T2-JUNE26", "startDate": "20261114", "startTime": "29:45:00",
             "scheduleRelationship": "CANCELED", "routeId": "10-13201", "directionId": 0},
    "timestamp": "1794680000"}})  # fmt: skip


def trip_report(entity: str, ts: int, rel: str, vehicle: str | None, stops: int) -> str:
    body: dict[str, Any] = {"trip": {"tripId": "T1-JUNE26", "startDate": "20261114",
                                     "startTime": "08:50:00", "scheduleRelationship": rel,
                                     "routeId": "2-13201", "directionId": 1},
                            "timestamp": str(ts)}  # fmt: skip
    if vehicle:
        body["vehicle"] = {"id": vehicle}
    if stops:
        body["stopTimeUpdate"] = [{"stopSequence": i + 1, "stopId": f"S{i}"} for i in range(stops)]
    return json.dumps({"id": entity, "tripUpdate": body})


# T1 published twice in one snapshot: a stale report without a vehicle, and a newer one with
# vehicle 3912 and two stop predictions (the pattern found on Nov 14-16).
T1_STALE = trip_report("T1-old", 1794679900, "SCHEDULED", None, 0)
T1_NEW = trip_report("T1-JUNE26", 1794680000, "SCHEDULED", "3912", 2)
# A trip ID from another service period: unmatched.
UNMATCHED = json.dumps({"id": "T9-SEPT21", "tripUpdate": {
    "trip": {"tripId": "T9-SEPT21", "startDate": "20261114", "startTime": "09:00:00",
             "routeId": "2-13201", "directionId": 0}, "timestamp": "1794680000"}})  # fmt: skip
# T2 canceled, then a newer SCHEDULED report under another entity: reinstated.
T2_BACK = json.dumps({"id": "T2-back", "tripUpdate": {
    "trip": {"tripId": "T2-JUNE26", "startDate": "20261114", "startTime": "29:45:00",
             "scheduleRelationship": "SCHEDULED", "routeId": "10-13201", "directionId": 0},
    "vehicle": {"id": "4001"}, "timestamp": "1794680100"}})  # fmt: skip


def run_dbt(data: Path, tmp: Path, tz: str = "America/Los_Angeles") -> Path:
    """`dbt build` into a fresh DuckDB file; returns a copy safe to open from the test."""
    db = tmp / "ghostbus.duckdb"
    env = {
        "GHOSTBUS_DUCKDB": str(db),  # profiles.yml reads it
        # Los Angeles, not UTC: SQL that relies on the session zone must fail here
        # (pipeline spec, section 5). test_the_build_does_not_depend_on_the_session_zone also
        # builds in a third zone, which catches SQL that quietly assumes Los Angeles.
        "GHOSTBUS_DBT_TZ": tz,
        "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",  # offline (hard rule 10)
    }
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        result = dbtRunner().invoke([
            "build", "--project-dir", str(DBT), "--profiles-dir", str(DBT),
            # The 3-trip world has 1 unmatched key of 3 on purpose; the real 0.80 floor is for
            # thousands of keys a day.
            "--vars", json.dumps({"data_dir": str(data), "match_rate_error": 0.5}),
            "--target-path", str(tmp / "target"), "--log-path", str(tmp / "logs"), "--quiet",
        ])  # fmt: skip
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    results: list[Any] = list(getattr(result.result, "results", None) or [])
    failures = [f"{r.node.name}: {r.status}: {r.message}" for r in results
                if str(r.status) not in ("success", "pass")]  # fmt: skip
    assert result.success, result.exception or failures
    # dbt keeps its DuckDB connection open in this process, and DuckDB won't open the same
    # file twice with different settings, so tests read a copy.
    # Recent writes may still be in the write-ahead log, so copy it too.
    copy = tmp / "readonly.duckdb"
    shutil.copy(db, copy)
    wal = db.with_name(db.name + ".wal")
    if wal.exists():
        shutil.copy(wal, copy.with_name(copy.name + ".wal"))
    return copy


def build_world(tmp: Path) -> Path:
    return build(
        tmp,
        # The same vehicle report in two fetches.
        [("2026-11-14T16:50:00Z", [VEHICLE]), ("2026-11-14T16:50:30Z", [VEHICLE])],
        [("2026-11-14T16:50:00Z", [CANCELED, T1_STALE, T1_NEW, UNMATCHED]),
         ("2026-11-14T16:51:00Z", [CANCELED, T2_BACK])],
    )  # fmt: skip
