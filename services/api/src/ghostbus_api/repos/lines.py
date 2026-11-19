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


# The lines of the schedule version in force on the local date, with their summary for one
# window (both directions pooled, ADR-026). Lines are kept unless known not to be Metro-operated
# (is_metro_operated is NULL until the contracted-lines seed). Ordered by number, named services
# last.
LIST_LINES = """
    WITH version AS (
        SELECT version_id FROM serving.schedule_version
        WHERE ever_in_force AND valid_from <= :today
        ORDER BY valid_from DESC LIMIT 1
    )
    SELECT l.line, l.line_slug, l.display_name, l.line_kind, l.schedule_version,
           s.n_trips, s.n_service_days, s.missed_rate, s.announced_rate, s.unplanned_rate,
           s.unplanned_share, s.missed_rate_ci_low, s.missed_rate_ci_high,
           s.unplanned_share_ci_low, s.unplanned_share_ci_high, s.suppressed
    FROM serving.line AS l
    JOIN version AS v ON l.schedule_version = v.version_id
    LEFT JOIN serving.line_summary AS s
        ON s.line = l.line AND s.direction_id IS NULL AND s.time_window = :window
    WHERE l.is_metro_operated IS DISTINCT FROM false
    ORDER BY l.line_number NULLS LAST, l.line
"""


def list_lines(con: Connection, today: date, window: str) -> list[dict[str, Any]]:
    rows = con.execute(text(LIST_LINES), {"today": today, "window": window}).mappings()
    return [dict(r) for r in rows]


def line_info(con: Connection, version: str, line: str) -> dict[str, Any]:
    row = (
        con.execute(
            text(
                "SELECT line_kind, description, route_color, route_text_color "
                "FROM serving.line WHERE schedule_version = :version AND line = :line"
            ),
            {"version": version, "line": line},
        )
        .mappings()
        .one()
    )
    return dict(row)


def directions(con: Connection, version: str, line: str) -> list[dict[str, Any]]:
    rows = con.execute(
        text(
            "SELECT direction_id, headsign, first_stop_name, last_stop_name "
            "FROM serving.line_direction WHERE schedule_version = :version AND line = :line "
            "ORDER BY direction_id"
        ),
        {"version": version, "line": line},
    ).mappings()
    return [dict(r) for r in rows]


def line_summaries(con: Connection, line: str, window: str) -> list[dict[str, Any]]:
    """Both-directions (direction_id NULL) and per-direction summaries for one window."""
    rows = con.execute(
        text(
            "SELECT direction_id, n_trips, n_service_days, missed_rate, announced_rate, "
            "unplanned_rate, unplanned_share, missed_rate_ci_low, missed_rate_ci_high, "
            "unplanned_share_ci_low, unplanned_share_ci_high, suppressed "
            "FROM serving.line_summary WHERE line = :line AND time_window = :window"
        ),
        {"line": line, "window": window},
    ).mappings()
    return [dict(r) for r in rows]


def stops(con: Connection, version: str, line: str, direction_id: int) -> list[dict[str, Any]]:
    rows = con.execute(
        text(
            "SELECT stop_order, stop_id, stop_code, stop_name, stop_lat, stop_lon, "
            "in_main_pattern FROM serving.line_stop "
            "WHERE schedule_version = :version AND line = :line AND direction_id = :direction_id "
            "ORDER BY stop_order"
        ),
        {"version": version, "line": line, "direction_id": direction_id},
    ).mappings()
    return [dict(r) for r in rows]
