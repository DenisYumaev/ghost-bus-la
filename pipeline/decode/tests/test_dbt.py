"""dbt build over a synthetic world pushed through the real Python pipeline.

Runs every model, grain test and dbt unit test (pipeline spec, sections 6 and 10). Offline:
the sources are local files written by compaction, decode and sync in this test.
"""

import json
import os
import shutil
from pathlib import Path
from typing import Any

import duckdb
import pytest
from dbt.cli.main import dbtRunner
from world import build

DBT = Path(__file__).parents[3] / "pipeline" / "dbt"

VEHICLE = json.dumps({"id": "3912", "vehicle": {
    "trip": {"tripId": "T1-JUNE26", "startDate": "20261114", "startTime": "08:50:00",
             "routeId": "2-13201", "directionId": 1},
    "position": {"latitude": 34.06, "longitude": -118.30}, "timestamp": "1794680000",
    "vehicle": {"id": "3912"}}})  # fmt: skip
CANCELED = json.dumps({"id": "T2-JUNE26", "tripUpdate": {
    "trip": {"tripId": "T2-JUNE26", "startDate": "20261114", "startTime": "29:45:00",
             "scheduleRelationship": "CANCELED", "routeId": "10-13201", "directionId": 0},
    "timestamp": "1794680000"}})  # fmt: skip


def run_dbt(data: Path, tmp: Path) -> Path:
    """`dbt build` into a fresh DuckDB file; returns a copy safe to open from the test."""
    db = tmp / "ghostbus.duckdb"
    env = {
        "GHOSTBUS_DUCKDB": str(db),  # profiles.yml reads it
        # Los Angeles, not UTC: SQL that relies on the session zone must fail here
        # (pipeline spec, section 5).
        "GHOSTBUS_DBT_TZ": "America/Los_Angeles",
        "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",  # offline (hard rule 10)
    }
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        result = dbtRunner().invoke([
            "build", "--project-dir", str(DBT), "--profiles-dir", str(DBT),
            "--vars", json.dumps({"data_dir": str(data)}),
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


@pytest.fixture(scope="module")
def warehouse(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp = tmp_path_factory.mktemp("dbt")
    data = build(tmp, [("2026-11-14T16:50:00Z", [VEHICLE])],
                 [("2026-11-14T16:50:00Z", [CANCELED])])  # fmt: skip
    return run_dbt(data, tmp)


def rows(db: Path, sql: str) -> list[tuple[Any, ...]]:
    with duckdb.connect(str(db), read_only=True) as con:
        return con.execute(sql).fetchall()


def test_dbt_build_passes_every_model_and_test(warehouse: Path) -> None:
    assert warehouse.exists()


def test_schedule_dims_come_from_the_extracted_version(warehouse: Path) -> None:
    assert rows(warehouse, "SELECT schedule_version, count(*) FROM dim_trips GROUP BY 1") == [
        ("cb1a2283abecc0af", 2)
    ]
    assert rows(warehouse, "SELECT line FROM dim_routes ORDER BY route_id") == [
        ("10/48",),
        ("2",),
        ("Dodger Stadium Express",),
    ]


def test_fetch_log_is_typed(warehouse: Path) -> None:
    got = rows(warehouse, "SELECT feed, outcome FROM stg_fetch_log ORDER BY feed")
    assert ("trip_updates", "written") in got
    assert ("vehicle_positions", "written") in got
