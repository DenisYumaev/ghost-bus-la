"""Queries for lines and their reliability (API spec section 10: repositories own SQL; all
queries are parameterized)."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import Connection, text


def normalize_slug(slug: str) -> str:
    """Slugs are lowercase (ADR-028); accept any case in URLs."""
    return slug.strip().lower()


@dataclass(frozen=True)
class LineDirection:
    line: str
    line_slug: str
    display_name: str
    direction_id: int
    headsign: str


# Both queries pick the schedule version in force on the rider's local date: the newest one
# in force at some point that starts on or before it (ADR-028: lines are per version).
FIND_LINE = """
    SELECT line, line_slug, display_name
    FROM serving.line
    WHERE line_slug = :slug
      AND schedule_version = (
          SELECT version_id FROM serving.schedule_version
          WHERE ever_in_force AND valid_from <= :today
          ORDER BY valid_from DESC LIMIT 1)
"""

FIND_DIRECTION = """
    SELECT headsign
    FROM serving.line_direction
    WHERE line = :line AND direction_id = :direction_id
      AND schedule_version = (
          SELECT version_id FROM serving.schedule_version
          WHERE ever_in_force AND valid_from <= :today
          ORDER BY valid_from DESC LIMIT 1)
"""


def find_line(con: Connection, slug: str, today: date) -> dict[str, Any] | None:
    row = (
        con.execute(text(FIND_LINE), {"today": today, "slug": normalize_slug(slug)})
        .mappings()
        .first()
    )
    return dict(row) if row else None


def find_direction(con: Connection, line: str, direction_id: int, today: date) -> str | None:
    params = {"today": today, "line": line, "direction_id": direction_id}
    headsign: str | None = con.execute(text(FIND_DIRECTION), params).scalar_one_or_none()
    return headsign


def data_as_of(con: Connection, table: str) -> datetime | None:
    """When the serving table was last published successfully (API spec section 1)."""
    return con.execute(
        text(
            "SELECT max(finished_at) FROM ops.publish_run "
            "WHERE table_name = :table AND status = 'succeeded'"
        ),
        {"table": table},
    ).scalar_one_or_none()


def reliability_cells(
    con: Connection, line: str, direction_id: int, window: str, day_type: str | None
) -> list[dict[str, Any]]:
    rows = con.execute(
        text(
            "SELECT day_type, hour_local, n_trips, missed_rate, announced_rate, unplanned_rate, "
            "ci_low, ci_high, suppressed, window_start, window_end "
            "FROM serving.reliability "
            "WHERE line = :line AND direction_id = :direction_id AND time_window = :window "
            "AND (CAST(:day_type AS text) IS NULL OR day_type = :day_type) "
            "ORDER BY CASE day_type WHEN 'weekday' THEN 0 WHEN 'saturday' THEN 1 ELSE 2 END, "
            "hour_local"
        ),
        {"line": line, "direction_id": direction_id, "window": window, "day_type": day_type},
    ).mappings()
    return [dict(r) for r in rows]


def has_cells(con: Connection, line: str, direction_id: int) -> bool:
    return bool(
        con.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM serving.reliability "
                "WHERE line = :line AND direction_id = :direction_id)"
            ),
            {"line": line, "direction_id": direction_id},
        ).scalar_one()
    )


def newest_publish(con: Connection) -> datetime | None:
    return con.execute(
        text("SELECT max(finished_at) FROM ops.publish_run WHERE status = 'succeeded'")
    ).scalar_one_or_none()
