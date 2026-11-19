"""Queries for the system summary and feed health (API spec section 4.1)."""

from typing import Any

from sqlalchemy import Connection, text


def summaries(con: Connection) -> list[dict[str, Any]]:
    rows = con.execute(
        text(
            "SELECT time_window, window_start, window_end, first_data_date, n_service_days, "
            "n_lines, n_scheduled, n_unknown, n_ran, n_partial, n_missed, n_missed_announced, "
            "n_missed_unplanned, n_trips, missed_rate, announced_rate, unplanned_rate, "
            "unplanned_share, "
            "missed_rate_ci_low, missed_rate_ci_high, unplanned_share_ci_low, "
            "unplanned_share_ci_high, suppressed FROM serving.system_summary "
            "ORDER BY CASE time_window WHEN '28d' THEN 0 WHEN '90d' THEN 1 ELSE 2 END"
        )
    ).mappings()
    return [dict(r) for r in rows]


def feed_health(con: Connection, hours: int) -> list[dict[str, Any]]:
    """The last `hours` of 5-minute buckets, counted back from the newest bucket published (not
    the clock: a stale table shows its own last day, and /readyz reports the staleness)."""
    rows = con.execute(
        text(
            "SELECT feed, bucket_start, n_fetches, n_success, n_errors, error_rate, "
            "freshest_age_s, healthy FROM serving.feed_health "
            "WHERE bucket_start > (SELECT max(bucket_start) FROM serving.feed_health) "
            "- make_interval(hours => :hours) "
            "ORDER BY bucket_start, feed"
        ),
        {"hours": hours},
    ).mappings()
    return [dict(r) for r in rows]
