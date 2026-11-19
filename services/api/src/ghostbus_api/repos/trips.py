"""Queries for the weekly trend and trip-level outcomes (API spec section 4.1)."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import Connection, text

# The last `weeks` Mondays counted back from the newest week across all lines (ADR-026), each
# with this line-direction's numbers if it has any: a week without trips is an empty point.
TREND = """
    WITH newest AS (SELECT max(week_start) AS week FROM serving.line_trend),
    weeks AS (  -- integer and date arithmetic only: no time zone involved
        SELECT week - 7 * g AS week_start
        FROM newest, generate_series(0, :weeks - 1) AS g
    )
    SELECT w.week_start, t.n_service_days, t.n_scheduled, t.n_unknown, t.n_trips, t.n_ran,
           t.n_partial, t.n_missed, t.n_missed_announced, t.n_missed_unplanned, t.missed_rate,
           t.announced_rate, t.unplanned_rate, t.suppressed
    FROM weeks AS w
    LEFT JOIN serving.line_trend AS t
        ON t.week_start = w.week_start AND t.line = :line AND t.direction_id = :direction_id
    ORDER BY w.week_start
"""


def trend(con: Connection, line: str, direction_id: int, weeks: int) -> list[dict[str, Any]]:
    params = {"line": line, "direction_id": direction_id, "weeks": weeks}
    return [dict(r) for r in con.execute(text(TREND), params).mappings()]


# One line's trips on one service date, keyset-paginated by (sched_start_utc, trip_id): the
# index (line, service_date, sched_start_utc, trip_id) serves it as a range scan.
OUTCOMES = """
    SELECT trip_id, direction_id, sched_start_utc, sched_end_utc, outcome, announced,
           advance_notice_s, stop_coverage
    FROM serving.trip_outcome_recent
    WHERE line = :line AND service_date = :service_date
      -- One predicate that is always an index range condition, even in a generic prepared plan;
      -- the first page compares against -infinity and '' (trip IDs are never empty).
      AND (sched_start_utc, trip_id) > (
          COALESCE(CAST(:after_start AS timestamptz), '-infinity'),
          COALESCE(CAST(:after_trip AS text), ''))
    ORDER BY sched_start_utc, trip_id
    LIMIT :limit
"""


def outcomes(
    con: Connection,
    line: str,
    service_date: date,
    after: tuple[datetime, str] | None,
    limit: int,
) -> list[dict[str, Any]]:
    params = {
        "line": line,
        "service_date": service_date,
        "after_start": after[0] if after else None,
        "after_trip": after[1] if after else None,
        "limit": limit,
    }
    return [dict(r) for r in con.execute(text(OUTCOMES), params).mappings()]
