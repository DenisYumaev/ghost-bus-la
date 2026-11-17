"""How the schedule encodes holidays: calendar_dates exceptions by date and service kind.

    uv run python scripts/research_holiday_service.py [data/ghostbus.duckdb]

Read-only. Backs int_service_day_types' rule that the schedule, not the calendar, decides a
service date's day type (docs/research/holiday-service.md).
"""

import sys

import duckdb

QUERY = """
    SELECT schedule_version, CAST(date AS VARCHAR) AS date, dayname(date) AS weekday,
           count(*) FILTER (WHERE exception_type = 2 AND service_id LIKE '%\\_Weekday' ESCAPE '\\')
               AS weekday_ids_removed,
           count(*) FILTER (WHERE exception_type = 1 AND service_id LIKE '%\\_Sunday' ESCAPE '\\')
               AS sunday_ids_added,
           count(*) FILTER (WHERE exception_type = 2) AS all_removed,
           count(*) FILTER (WHERE exception_type = 1) AS all_added
    FROM src_gtfs_calendar_dates
    GROUP BY ALL
    HAVING sunday_ids_added > 0
    ORDER BY 1, 2
"""


def main() -> None:
    db = sys.argv[1] if len(sys.argv) > 1 else "data/ghostbus.duckdb"
    with duckdb.connect(db, read_only=True) as con:
        cur = con.execute(QUERY)
        print(" | ".join(d[0] for d in cur.description))
        for row in cur.fetchall():
            print(" | ".join(str(v) for v in row))
        (n_patterns,) = con.execute(
            "SELECT count(*) FROM src_gtfs_calendar"
            " WHERE (saturday + sunday > 0"
            " AND monday + tuesday + wednesday + thursday + friday > 0)"
            " OR (saturday = 1 AND sunday = 1)"
        ).fetchall()[0]
        print(f"mixed weekly patterns in calendar.txt: {n_patterns}")


if __name__ == "__main__":
    main()
