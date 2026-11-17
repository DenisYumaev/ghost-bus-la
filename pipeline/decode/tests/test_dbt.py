"""dbt build over a synthetic world pushed through the real Python pipeline.

Runs every model, grain test and dbt unit test (pipeline spec, sections 6 and 10). Offline:
the sources are local files written by compaction, decode and sync in this test.
"""

import json
import os
import shutil
from datetime import date
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


def _world(tmp: Path) -> Path:
    return build(
        tmp,
        # The same vehicle report in two fetches.
        [("2026-11-14T16:50:00Z", [VEHICLE]), ("2026-11-14T16:50:30Z", [VEHICLE])],
        [("2026-11-14T16:50:00Z", [CANCELED, T1_STALE, T1_NEW, UNMATCHED]),
         ("2026-11-14T16:51:00Z", [CANCELED, T2_BACK])],
    )  # fmt: skip


@pytest.fixture(scope="module")
def warehouse(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp = tmp_path_factory.mktemp("dbt")
    return run_dbt(_world(tmp), tmp)


def test_the_build_does_not_depend_on_the_session_zone(
    warehouse: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """The same world built in Asia/Kolkata (UTC+5:30) gives the same warehouse, and every unit
    test passes there too: no model relies on the session being UTC or Los Angeles."""
    from fingerprint_warehouse import fingerprints

    tmp = tmp_path_factory.mktemp("dbt_kolkata")
    other = run_dbt(_world(tmp), tmp, tz="Asia/Kolkata")
    with (
        duckdb.connect(str(warehouse), read_only=True) as a,
        duckdb.connect(str(other), read_only=True) as b,
    ):
        fa, fb = fingerprints(a), fingerprints(b)
    # Views over the world's files read different temp directories; compare everything else,
    # and the views' rows, which don't contain the path.
    assert {k: v for k, v in fa.items() if not k.startswith("main.src_")} == {
        k: v for k, v in fb.items() if not k.startswith("main.src_")
    }


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


def test_vehicle_reports_are_deduplicated_across_fetches(warehouse: Path) -> None:
    assert rows(warehouse, "SELECT vehicle_id, n_snapshots, n_trips, service_date "
                "FROM stg_vehicle_positions") == [("3912", 2, 1, date(2026, 11, 14))]  # fmt: skip


def test_a_trip_published_twice_keeps_the_newer_report(warehouse: Path) -> None:
    sql = (
        "SELECT entity_key, is_chosen, n_reports, n_stop_updates FROM stg_trip_reports "
        "WHERE trip_id = 'T1-JUNE26' ORDER BY entity_key"
    )
    reports = rows(warehouse, sql)
    assert reports == [("T1-JUNE26", True, 2, 2), ("T1-old", False, 2, 0)]
    stops = rows(warehouse, "SELECT stop_key, vehicle_id FROM stg_trip_updates "
                 "WHERE trip_id = 'T1-JUNE26' ORDER BY stop_key")  # fmt: skip
    assert stops == [(1, "3912"), (2, "3912")]


def test_a_cancellation_followed_by_a_newer_scheduled_report_is_reinstated(
    warehouse: Path,
) -> None:
    sql = (
        "SELECT service_date, n_snapshots, reinstated, "
        "CAST(timezone('UTC', first_seen_at) AS VARCHAR) FROM stg_cancellations"
    )
    got = rows(warehouse, sql)
    # Fetch 2's chosen state is the newer SCHEDULED report, so one canceled fetch.
    assert got == [(date(2026, 11, 14), 1, True, "2026-11-14 16:50:00")]


def test_the_schedule_expands_end_to_end(warehouse: Path) -> None:
    assert rows(warehouse, "SELECT service_date, schedule_version FROM int_service_dates") == [
        (date(2026, 11, 14), "cb1a2283abecc0af")
    ]
    sql = (
        "SELECT trip_id, n_stops, block_id, CAST(timezone('UTC', sched_start_utc) AS VARCHAR), "
        "CAST(timezone('UTC', sched_end_utc) AS VARCHAR) FROM int_schedule_expanded "
        "ORDER BY trip_id"
    )
    assert rows(warehouse, sql) == [
        # 08:50-09:05 PST on Saturday Nov 14 (added by calendar_dates).
        ("T1-JUNE26", 3, "2065100", "2026-11-14 16:50:00", "2026-11-14 17:05:00"),
        # 29:45 on service date Nov 14 is 05:45 PST on Nov 15.
        ("T2-JUNE26", 1, None, "2026-11-15 13:45:00", "2026-11-15 13:45:00"),
    ]


def test_realtime_trips_are_matched_through_the_crosswalk(warehouse: Path) -> None:
    sql = (
        "SELECT trip_id, sources, scheduled_trip_id, match_method, in_scope "
        "FROM int_trip_crosswalk ORDER BY trip_id"
    )
    assert rows(warehouse, sql) == [
        ("T1-JUNE26", ["trip_updates", "vehicle_positions"], "T1-JUNE26", "exact", True),
        ("T2-JUNE26", ["trip_updates"], "T2-JUNE26", "exact", True),
        ("T9-SEPT21", ["trip_updates"], None, "unmatched", True),
    ]


def test_observations_end_to_end(warehouse: Path) -> None:
    sql = (
        "SELECT trip_id, n_positions, vehicle_ids, max_stop_sequence, n_updates_with_vehicle, "
        "observed_running, rt_canceled, CAST(timezone('UTC', first_seen_utc) AS VARCHAR) "
        "FROM int_trip_observations ORDER BY trip_id"
    )
    assert rows(warehouse, sql) == [
        # T1: vehicle 3912 at 16:50 UTC and a chosen SCHEDULED report with it.
        # One position: the same report in two fetches is one report after the dedupe.
        ("T1-JUNE26", 1, ["3912"], 2, 1, True, False, "2026-11-14 16:50:00"),
        # T2 (29:45, window 13:15-14:45 UTC Nov 15): nothing in the window; its cancellation
        # was withdrawn at 16:51 Nov 14, long before the start.
        ("T2-JUNE26", 0, None, None, 0, False, False, None),
    ]


def test_outcomes_end_to_end(warehouse: Path) -> None:
    sql = (
        "SELECT trip_id, outcome, round(stop_coverage, 3), feed_healthy_share, announced "
        "FROM fct_trip_outcomes ORDER BY trip_id"
    )
    assert rows(warehouse, sql) == [
        # T1: vehicle 3912 reached stop 2 of 3 after the start -> coverage 0.667 -> partial.
        # Its window (16:20-18:05 UTC) has 21 buckets; the world fetched only at 16:50.
        ("T1-JUNE26", "partial", 0.667, 1 / 21, False),
        # T2: not observed; nothing was fetched during its window (13:15-14:45 UTC Nov 15),
        # so feeds count as unhealthy there -> unknown, not missed.
        ("T2-JUNE26", "unknown", None, 0.0, False),
    ]


def test_feed_health_end_to_end(warehouse: Path) -> None:
    # 3 synced UTC days x 288 five-minute buckets x 2 feeds.
    assert rows(warehouse, "SELECT count(*) FROM fct_feed_health") == [(1728,)]
    healthy = rows(warehouse, "SELECT feed, CAST(timezone('UTC', bucket_start) AS VARCHAR), "
                   "n_success FROM fct_feed_health WHERE healthy ORDER BY feed")  # fmt: skip
    assert healthy == [
        ("trip_updates", "2026-11-14 16:50:00", 2),
        ("vehicle_positions", "2026-11-14 16:50:00", 2),
    ]


def test_the_acceptance_query_reports_a_line_and_refuses_an_empty_one(warehouse: Path) -> None:
    import subprocess
    import sys

    script = str(DBT.parents[1] / "scripts" / "line_day_summary.py")
    ok = subprocess.run([sys.executable, script, "2", "2026-11-14", str(warehouse)],  # noqa: S603
                        capture_output=True, text=True, check=False)  # fmt: skip
    assert ok.returncode == 0, ok.stderr
    assert "scheduled: 1" in ok.stdout
    assert "partial: 1" in ok.stdout
    empty = subprocess.run([sys.executable, script, "999", "2026-11-14", str(warehouse)],  # noqa: S603
                           capture_output=True, text=True, check=False)  # fmt: skip
    assert empty.returncode == 1


def test_reliability_end_to_end(warehouse: Path) -> None:
    # Nov 14 is a Saturday, but its only service is the fixture's Sunday-only service added by
    # calendar_dates (as on a holiday), so the schedule makes it a sunday.
    day = (
        "SELECT CAST(service_date AS VARCHAR), day_type, day_type_source FROM int_service_day_types"
    )
    assert rows(warehouse, day) == [("2026-11-14", "sunday", "schedule")]
    # Two trips (T2 unknown, so one in the denominator): far below the thresholds, so counts
    # but no rates, in every window.
    sql = (
        "SELECT time_window, day_type, sum(n_scheduled), sum(n_trips), bool_and(suppressed),"
        " count(missed_rate) FROM fct_reliability GROUP BY 1, 2 ORDER BY 1"
    )
    assert rows(warehouse, sql) == [
        ("28d", "sunday", 2, 1, True, 0),
        ("90d", "sunday", 2, 1, True, 0),
        ("all", "sunday", 2, 1, True, 0),
    ]
