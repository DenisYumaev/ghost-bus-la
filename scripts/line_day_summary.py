"""M1's acceptance query: for a line and service date, how many trips were scheduled and ran.

    uv run python scripts/line_day_summary.py 754 2026-11-15 [data/ghostbus.duckdb]
    uv run python scripts/line_day_summary.py all 2026-11-15   # every line

Reads fct_trip_outcomes from the local dbt build (make dbt-sync, make dbt); read-only. Also
checks the reconciliation identity (scheduled = sum of outcomes, pipeline spec section 10).
Internal numbers: nothing here is quotable until M5 validates against Metro's report, and
M1's missed count includes trips M4 may reclassify as likely_untracked (ADR-024).
"""

import sys
from datetime import date

import duckdb

QUERY = """
    SELECT count(*) AS scheduled,
           count(*) FILTER (WHERE outcome = 'ran') AS ran,
           count(*) FILTER (WHERE outcome = 'partial') AS partial,
           count(*) FILTER (WHERE outcome = 'missed') AS missed,
           count(*) FILTER (WHERE outcome = 'unknown') AS unknown,
           count(*) FILTER (WHERE outcome = 'missed' AND announced) AS missed_announced,
           count(*) FILTER (WHERE outcome = 'missed' AND NOT announced) AS missed_unannounced,
           count(*) FILTER (WHERE outcome = 'ran' AND announced) AS ran_though_announced
    FROM fct_trip_outcomes
    WHERE (line = ? OR ? = 'all') AND service_date = ?
"""


def main() -> None:
    line, day = sys.argv[1], date.fromisoformat(sys.argv[2])
    db = sys.argv[3] if len(sys.argv) > 3 else "data/ghostbus.duckdb"
    with duckdb.connect(db, read_only=True) as con:
        cur = con.execute(QUERY, [line, line, day])
        names = [d[0] for d in cur.description]
        row = dict(zip(names, cur.fetchall()[0], strict=True))
    parts = row["ran"] + row["partial"] + row["missed"] + row["unknown"]
    print(f"line {line}, service date {day}:")
    for name in names:
        print(f"  {name:>20}: {row[name]}")
    print(f"  reconciliation: scheduled {row['scheduled']} = outcomes {parts}: "
          f"{'ok' if parts == row['scheduled'] else 'MISMATCH'}")  # fmt: skip


if __name__ == "__main__":
    main()
