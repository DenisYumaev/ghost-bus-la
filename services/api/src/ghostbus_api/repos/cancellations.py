"""Queries for current cancellations (API spec section 4.1; ADR-029)."""

from datetime import date
from typing import Any

from sqlalchemy import Connection, text

# Names come from the schedule version in force today; a canceled trip of a line missing from
# it still appears, with its Metro name only.
CURRENT = """
    WITH version AS (
        SELECT v.version_id FROM serving.schedule_version AS v
        WHERE v.ever_in_force AND v.valid_from <= :today
          AND EXISTS (SELECT 1 FROM serving.line AS l WHERE l.schedule_version = v.version_id)
        ORDER BY v.valid_from DESC LIMIT 1
    )
    SELECT c.service_date, c.trip_id, c.line, l.line_slug, l.display_name, c.direction_id,
           d.headsign, c.sched_start_utc, c.canceled_first_seen_at, c.advance_notice_s, c.as_of
    FROM serving.cancellation_current AS c
    LEFT JOIN version AS v ON true
    LEFT JOIN serving.line AS l ON l.schedule_version = v.version_id AND l.line = c.line
    LEFT JOIN serving.line_direction AS d
        ON d.schedule_version = v.version_id AND d.line = c.line
        AND d.direction_id = c.direction_id
    WHERE CAST(:line AS text) IS NULL OR c.line = :line
    ORDER BY c.sched_start_utc, c.trip_id
"""


def current(con: Connection, today: date, line: str | None) -> list[dict[str, Any]]:
    rows = con.execute(text(CURRENT), {"today": today, "line": line}).mappings()
    return [dict(r) for r in rows]
