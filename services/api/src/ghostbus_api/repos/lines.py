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


# The line as of the rider's local date: the newest schedule version in force by then that
# contains this line. Choosing the version from serving.line itself means a publish that has
# swapped schedule_version but not yet line can't make every line vanish, and a discontinued
# line still resolves to its last version (reliability is keyed by line, so its history stays).
FIND_LINE = """
    SELECT l.line, l.line_slug, l.display_name, l.schedule_version
    FROM serving.line AS l
    JOIN serving.schedule_version AS v ON v.version_id = l.schedule_version
    WHERE l.line_slug = :slug AND v.ever_in_force AND v.valid_from <= :today
    ORDER BY v.valid_from DESC
    LIMIT 1
"""

FIND_DIRECTION = """
    SELECT headsign
    FROM serving.line_direction
    WHERE schedule_version = :version AND line = :line AND direction_id = :direction_id
"""


def find_line(con: Connection, slug: str, today: date) -> dict[str, Any] | None:
    """`today` is the Los Angeles calendar date (hard rule 5: rider-facing lookups use the local
    day). Between midnight and the end of the previous service day on a service-change date this
    already picks the new version; only headsign and name could differ."""
    row = (
        con.execute(text(FIND_LINE), {"today": today, "slug": normalize_slug(slug)})
        .mappings()
        .first()
    )
    return dict(row) if row else None


def find_direction(con: Connection, version: str, line: str, direction_id: int) -> str | None:
    params = {"version": version, "line": line, "direction_id": direction_id}
    headsign: str | None = con.execute(text(FIND_DIRECTION), params).scalar_one_or_none()
    return headsign


def window_bounds(con: Connection, window: str) -> dict[str, Any] | None:
    """The window's dates: int_windows is global, so system_summary carries them for every
    window even when a line has no cells in it."""
    row = (
        con.execute(
            text(
                "SELECT window_start, window_end FROM serving.system_summary "
                "WHERE time_window = :window"
            ),
            {"window": window},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def data_as_of(con: Connection, table: str) -> datetime | None:
    """When the serving table was last published successfully (API spec section 1). The request
    stays in one transaction, and the publish_run row commits with its table's swap, so this
    and the rows read next come from the same publish. Don't switch reads to autocommit."""
    as_of: datetime | None = con.execute(
        text(
            "SELECT max(finished_at) FROM ops.publish_run "
            "WHERE table_name = :table AND status = 'succeeded'"
        ),
        {"table": table},
    ).scalar_one_or_none()
    return as_of


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


def stalest_publish(con: Connection) -> datetime | None:
    """The oldest of each serving table's latest successful publish: readiness means every
    table is fresh, so one table failing for days can't hide behind the others."""
    stalest: datetime | None = con.execute(
        text(
            "SELECT min(latest) FROM (SELECT table_name, max(finished_at) AS latest "
            "FROM ops.publish_run WHERE status = 'succeeded' GROUP BY table_name) AS t"
        )
    ).scalar_one_or_none()
    return stalest
