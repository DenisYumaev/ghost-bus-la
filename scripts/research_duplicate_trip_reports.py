"""Measure duplicate trip reports and late SCHEDULED reports in decoded trip updates.

    uv run python scripts/research_duplicate_trip_reports.py [data/ghostbus.duckdb]

Reads the local dbt build (run `make dbt-sync` and `make dbt` first); read-only. The query
behind docs/research/duplicate-trip-reports.md (hard rule 11).
"""

import sys

import duckdb

DB = sys.argv[1] if len(sys.argv) > 1 else "data/ghostbus.duckdb"

QUERIES = {
    "trip-fetches (distinct trip, service date, fetch)": """
        SELECT count(*) FROM (SELECT DISTINCT trip_id, start_date, fetched_at FROM src_trip_update)
    """,
    "trip-fetches with more than one report": """
        SELECT count(*) FROM (
            SELECT trip_id, start_date, fetched_at FROM src_trip_update
            GROUP BY ALL HAVING count(DISTINCT (entity_ts, vehicle_id)) > 1)
    """,
    "...of which the reports disagree on CANCELED vs SCHEDULED": """
        SELECT count(*) FROM (
            SELECT trip_id, start_date, fetched_at FROM src_trip_update
            GROUP BY ALL
            HAVING count(DISTINCT coalesce(trip_schedule_relationship, 'SCHEDULED')) > 1)
    """,
    "...disagreeing, by which relationship the newest report carries": """
        WITH c AS (
            SELECT trip_id, start_date, fetched_at FROM src_trip_update GROUP BY ALL
            HAVING count(DISTINCT coalesce(trip_schedule_relationship, 'SCHEDULED')) > 1),
        r AS (
            SELECT u.*, row_number() OVER (
                PARTITION BY u.trip_id, u.start_date, u.fetched_at
                ORDER BY u.entity_ts DESC NULLS LAST, u.vehicle_id NULLS LAST) AS rn
            FROM src_trip_update u JOIN c USING (trip_id, start_date, fetched_at))
        SELECT coalesce(trip_schedule_relationship, 'SCHEDULED') AS newest, count(*)
        FROM r WHERE rn = 1 GROUP BY 1 ORDER BY 1
    """,
    "...disagreeing, newest report has a vehicle / has none": """
        WITH c AS (
            SELECT trip_id, start_date, fetched_at FROM src_trip_update GROUP BY ALL
            HAVING count(DISTINCT coalesce(trip_schedule_relationship, 'SCHEDULED')) > 1),
        r AS (
            SELECT u.*, row_number() OVER (
                PARTITION BY u.trip_id, u.start_date, u.fetched_at
                ORDER BY u.entity_ts DESC NULLS LAST, u.vehicle_id NULLS LAST) AS rn
            FROM src_trip_update u JOIN c USING (trip_id, start_date, fetched_at))
        SELECT vehicle_id IS NOT NULL AS has_vehicle, count(*) FROM r WHERE rn = 1
        GROUP BY 1 ORDER BY 1
    """,
    "canceled trips (service date Nov 15) with a SCHEDULED report after the last CANCELED": """
        SELECT count(*) FROM stg_cancellations
        WHERE service_date = DATE '2026-11-15' AND reinstated
    """,
    "...of which a SCHEDULED report after the last CANCELED came before the scheduled start": """
        WITH c AS (SELECT * FROM stg_cancellations WHERE service_date = DATE '2026-11-15'),
        sched AS (
            SELECT trip_id, min(departure_s) AS start_s
            FROM dim_stop_times WHERE stop_sequence = 1 GROUP BY 1),
        later AS (
            SELECT c.trip_id,
                   max(u.fetched_at) FILTER (
                       WHERE u.fetched_at < timezone('America/Los_Angeles',
                             c.service_date + INTERVAL 12 HOUR) - INTERVAL 12 HOUR
                             + s.start_s * INTERVAL 1 SECOND) AS before_start
            FROM c
            JOIN stg_trip_updates u USING (trip_id, service_date)
            JOIN sched s USING (trip_id)
            WHERE u.trip_schedule_relationship = 'SCHEDULED' AND u.fetched_at > c.last_seen_at
            GROUP BY c.trip_id)
        SELECT count(*) FILTER (WHERE before_start IS NOT NULL), count(*) FROM later
    """,
}


def main() -> None:
    with duckdb.connect(DB, read_only=True) as con:
        con.execute("SET TimeZone = 'UTC'")
        for label, sql in QUERIES.items():
            print(f"{label}: {con.execute(sql).fetchall()}")


if __name__ == "__main__":
    main()
