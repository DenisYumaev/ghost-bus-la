"""The serving tables (API spec section 7; ADR-007, ADR-025, ADR-026): source query, key and
indexes per table. Each index matches what its endpoint filters by; M5 checks the plans."""

from ghostbus_publish.engine import ServingTable

# Trip-level outcomes and feed health are kept for a recent window only (API spec section 7).
RECENT_OUTCOME_DAYS = 35
FEED_HEALTH_DAYS = 7

TABLES: tuple[ServingTable, ...] = (
    ServingTable(
        "schedule_version",
        "SELECT * FROM dim_schedule_version",
        key=("version_id",),
        max_change=None,  # grows by one row per new schedule ZIP
    ),
    ServingTable(
        "line",
        "SELECT * FROM dim_line",
        key=("schedule_version", "line"),
        indexes=(("schedule_version", "line_slug"),),  # the API resolves URLs by slug
        max_change=None,  # every version ever in force: roughly doubles when a new ZIP lands
    ),
    ServingTable(
        "line_direction",
        "SELECT * FROM dim_line_direction",
        key=("schedule_version", "line", "direction_id"),
        max_change=None,
    ),
    ServingTable(
        "line_stop",
        "SELECT * FROM dim_line_stop",
        key=("schedule_version", "line", "direction_id", "stop_id"),
        indexes=(("schedule_version", "line", "direction_id", "stop_order"),),
        max_change=None,
    ),
    ServingTable(
        "reliability",
        "SELECT * FROM fct_reliability",
        key=("line", "direction_id", "time_window", "day_type", "hour_local"),
    ),
    ServingTable(
        "line_summary",
        "SELECT * FROM fct_line_summary",
        key=("line", "direction_id", "time_window"),
        # direction_id NULL is the both-directions row (ADR-026).
        nullable_key=frozenset({"direction_id"}),
        # GET /v1/lines: every line's both-directions row for one window.
        indexes=(("time_window", "direction_id"),),
    ),
    ServingTable(
        "line_trend",
        "SELECT * FROM fct_line_trend",
        key=("line", "direction_id", "week_start"),
        indexes=(("week_start",),),  # the newest week across all lines anchors the chart
        max_change=None,  # one more week every week: +50% at week 3
    ),
    ServingTable(
        "system_summary",
        "SELECT * FROM fct_system_summary",
        key=("time_window",),
    ),
    ServingTable(
        "trip_outcome_recent",
        # RECENT_OUTCOME_DAYS days; a literal, so the query is plain text (no f-string SQL).
        "SELECT * FROM fct_trip_outcomes WHERE service_date > "
        "(SELECT max(service_date) FROM fct_trip_outcomes) - 35",
        key=("service_date", "schedule_version", "trip_id"),
        # The trip list: one line and date, keyset-paginated by start time.
        indexes=(("line", "service_date", "sched_start_utc", "trip_id"),),
    ),
    ServingTable(
        "cancellation_current",
        "SELECT * FROM fct_current_cancellations",
        key=("service_date", "trip_id"),
        max_change=None,  # from none to dozens within minutes: the guard means nothing here
        allow_empty=True,  # nothing canceled right now is a normal state
        default=False,  # the open-date build publishes it (--only); ADR-029
    ),
    ServingTable(
        "cancellation_as_of",
        # One row: how current the list is, even when it's empty (ADR-029).
        "SELECT 'trip_updates' AS feed, as_of FROM fct_current_cancellations_as_of",
        key=("feed",),
        max_change=None,
        default=False,
    ),
    ServingTable(
        "method_param",
        # Both halves: the nightly one is rebuilt with the intervals it describes (ADR-027).
        "SELECT * FROM dim_method_params UNION ALL SELECT * FROM dim_method_params_nightly",
        key=("name",),
        max_change=None,  # a handful of rows; a new threshold is a legitimate change
    ),
    ServingTable(
        "feed_health",
        # FEED_HEALTH_DAYS days. Padding buckets (the synced days either side of the range) are
        # left out: once the open day syncs they lie in the future and would read as outages.
        "SELECT * FROM fct_feed_health WHERE NOT is_padding AND bucket_start > "
        "(SELECT max(bucket_start) FROM fct_feed_health WHERE NOT is_padding) - INTERVAL 7 DAY",
        key=("feed", "bucket_start"),
        indexes=(("bucket_start",),),  # the status page asks for the last N hours, all feeds
    ),
)
