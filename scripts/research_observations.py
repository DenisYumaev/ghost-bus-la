"""Measure trip matching and observations for one service date.

    uv run python scripts/research_observations.py [2026-11-15] [data/ghostbus.duckdb]

Reads the local dbt build (make dbt-sync, make dbt); read-only. The query behind
docs/research/observations.md (hard rule 11).
"""

# ruff: noqa: S608 - the only interpolated value is DAY, validated as an ISO date below.
import sys
from datetime import date

import duckdb

DAY = date.fromisoformat(sys.argv[1] if len(sys.argv) > 1 else "2026-11-15").isoformat()
DB = sys.argv[2] if len(sys.argv) > 2 else "data/ghostbus.duckdb"
D = f"DATE '{DAY}'"

# Per scheduled trip: positions before / at-or-after the scheduled start, and progress.
POS = f"""
    WITH o AS (SELECT * FROM int_trip_observations WHERE service_date = {D}),
    p AS (
        SELECT o.trip_id,
               count(*) FILTER (WHERE v.vehicle_ts < o.sched_start_utc) AS before_start,
               count(*) FILTER (WHERE v.vehicle_ts >= o.sched_start_utc) AS after_start,
               max(v.current_stop_sequence) FILTER (WHERE v.vehicle_ts >= o.sched_start_utc)
                   AS max_seq_after_start,
               max(v.first_fetched_at) AS last_position_fetched_at
        FROM o JOIN stg_vehicle_positions v
            ON v.trip_id = o.trip_id AND v.service_date = o.service_date
           AND v.vehicle_ts BETWEEN o.window_start AND o.window_end
        GROUP BY o.trip_id)
    SELECT o.*, coalesce(p.before_start, 0) AS before_start,
           coalesce(p.after_start, 0) AS after_start, p.max_seq_after_start,
           p.last_position_fetched_at
    FROM o LEFT JOIN p USING (trip_id)
"""

QUERIES = {
    "crosswalk keys in scope, by match method": f"""
        SELECT match_method, count(*) FROM int_trip_crosswalk
        WHERE service_date = {D} GROUP BY 1 ORDER BY 1""",
    "scheduled, observed, by positions, by updates only": f"""
        SELECT count(*), count(*) FILTER (WHERE observed_running),
               count(*) FILTER (WHERE n_positions > 0),
               count(*) FILTER (WHERE n_positions = 0 AND n_updates_with_vehicle > 0)
        FROM int_trip_observations WHERE service_date = {D}""",
    "rt_canceled; rt_canceled and observed": f"""
        SELECT count(*) FILTER (WHERE rt_canceled),
               count(*) FILTER (WHERE rt_canceled AND observed_running)
        FROM int_trip_observations WHERE service_date = {D}""",
    "canceled+observed: with positions after the start / only before it / updates only": f"""
        SELECT count(*) FILTER (WHERE after_start > 0),
               count(*) FILTER (WHERE after_start = 0 AND before_start > 0),
               count(*) FILTER (WHERE before_start = 0 AND after_start = 0)
        FROM ({POS}) WHERE rt_canceled AND observed_running""",
    "canceled+observed: reinstated after start (late SCHEDULED) / never reinstated": f"""
        SELECT count(*) FILTER (WHERE reinstated_at IS NOT NULL),
               count(*) FILTER (WHERE reinstated_at IS NULL)
        FROM int_trip_observations
        WHERE service_date = {D} AND rt_canceled AND observed_running""",
    "canceled+observed with positions after start: coverage after start p25/p50/p75": f"""
        SELECT quantile_cont(max_seq_after_start / n_stops, [0.25, 0.5, 0.75])
        FROM ({POS}) WHERE rt_canceled AND observed_running AND after_start > 0""",
    "canceled+observed: cancellation first seen after the last position fetch": f"""
        SELECT count(*) FILTER (WHERE canceled_first_seen_at > last_position_fetched_at),
               count(*) FILTER (WHERE last_position_fetched_at IS NOT NULL)
        FROM ({POS}) WHERE rt_canceled AND observed_running""",
    "all observed trips: positions only before the start (no position after it)": f"""
        SELECT count(*) FILTER (WHERE after_start = 0 AND before_start > 0),
               count(*) FILTER (WHERE observed_running)
        FROM ({POS})""",
    "observed by positions: coverage (max_stop_sequence / n_stops) p10/p25/p50": f"""
        SELECT quantile_cont(max_stop_sequence / n_stops, [0.1, 0.25, 0.5])
        FROM int_trip_observations WHERE service_date = {D} AND n_positions > 0""",
}


def main() -> None:
    with duckdb.connect(DB, read_only=True) as con:
        con.execute("SET TimeZone = 'UTC'")
        for label, sql in QUERIES.items():
            print(f"{label}: {con.execute(sql).fetchall()}")


if __name__ == "__main__":
    main()
