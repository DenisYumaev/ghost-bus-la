"""Queries for current cancellations (API spec section 4.1; ADR-029)."""

from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

# Names and headsigns from each trip's own schedule version (correct across a service change).
CURRENT = """
    SELECT c.service_date, c.trip_id, c.line, l.line_slug, l.display_name, c.direction_id,
           d.headsign, c.sched_start_utc, c.canceled_first_seen_at, c.advance_notice_s
    FROM serving.cancellation_current AS c
    LEFT JOIN serving.line AS l ON l.schedule_version = c.schedule_version AND l.line = c.line
    LEFT JOIN serving.line_direction AS d
        ON d.schedule_version = c.schedule_version AND d.line = c.line
        AND d.direction_id = c.direction_id
    WHERE CAST(:line AS text) IS NULL OR c.line = :line
    ORDER BY c.sched_start_utc, c.trip_id
"""


def current(con: Connection, line: str | None) -> list[dict[str, Any]]:
    rows = con.execute(text(CURRENT), {"line": line}).mappings()
    return [dict(r) for r in rows]


def as_of(con: Connection) -> datetime | None:
    """The newest feed fetch the list reflects, published even when the list is empty."""
    value: datetime | None = con.execute(
        text("SELECT as_of FROM serving.cancellation_as_of WHERE feed = 'trip_updates'")
    ).scalar_one_or_none()
    return value
