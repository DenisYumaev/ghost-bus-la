"""Example responses for the OpenAPI document (API spec section 1: every endpoint has one).
Method strings are copied from the real ones (routers/meta.py, dim_method_params).

Illustrative only, never measured (hard rule 11): the numbers are made up to be internally
consistent, such as counts that add up. `test_openapi.py` validates each one against its model.
"""

from typing import Any

from pydantic import ConfigDict

AS_OF = "2026-12-01T17:40:12Z"

# n_trips = scheduled - unknown; missed = announced + unplanned; rates are counts / n_trips.
RATES: dict[str, Any] = {
    "n_scheduled": 1240, "n_unknown": 12, "n_ran": 1150, "n_partial": 20, "n_missed": 58,
    "n_missed_announced": 30, "n_missed_unplanned": 28, "n_trips": 1228, "n_service_days": 17,
    "missed_rate": 0.0472, "announced_rate": 0.0244, "unplanned_rate": 0.0228,
    "unplanned_share": 0.4828, "missed_rate_ci_low": 0.0381, "missed_rate_ci_high": 0.0569,
    "unplanned_share_ci_low": 0.3621, "unplanned_share_ci_high": 0.6034, "suppressed": False,
}  # fmt: skip


def examples(*bodies: dict[str, Any]) -> ConfigDict:
    """A model_config that attaches these example bodies to the model's schema."""
    return ConfigDict(json_schema_extra={"examples": list(bodies)})


LINE_LIST = {
    "window": "28d", "window_start": "2026-11-04", "data_through": "2026-12-01",
    "data_as_of": AS_OF,
    "lines": [{
        "line": "720", "line_slug": "720", "display_name": "720", "line_kind": "rapid",
        "summary": RATES,
    }],
}  # fmt: skip

LINE_DETAIL = {
    "line": "720", "line_slug": "720", "display_name": "720", "line_kind": "rapid",
    "description": None, "route_color": "D11242", "route_text_color": "FFFFFF",
    "window": "28d", "data_through": "2026-12-01", "data_as_of": AS_OF, "summary": RATES,
    "directions": [{
        "direction_id": 0, "headsign": "Santa Monica", "first_stop_name": "Commerce",
        "last_stop_name": "Santa Monica", "summary": RATES,
    }],
}  # fmt: skip

STOP_LIST = {
    "line": "720", "line_slug": "720", "direction_id": 0, "headsign": "Santa Monica",
    "data_as_of": AS_OF,
    "stops": [{
        "stop_order": 1, "stop_id": "12345", "stop_code": "12345",
        "stop_name": "Wilshire / Vermont",
        "stop_lat": 34.0622, "stop_lon": -118.2917, "in_main_pattern": True,
    }],
}  # fmt: skip

TREND = {
    "line": "720", "line_slug": "720", "direction_id": 0, "headsign": "Santa Monica",
    "weeks": 12, "data_as_of": AS_OF,
    "points": [{
        "week_start": "2026-11-23", "n_service_days": 7, "n_scheduled": 310, "n_unknown": 3,
        "n_trips": 307, "n_ran": 288, "n_partial": 5, "n_missed": 14, "n_missed_announced": 8,
        "n_missed_unplanned": 6, "missed_rate": 0.0456, "announced_rate": 0.0261,
        "unplanned_rate": 0.0195, "suppressed": False,
    }],
}  # fmt: skip

TRIP_OUTCOMES = {
    "line": "720", "line_slug": "720", "service_date": "2026-11-30", "data_as_of": AS_OF,
    "trips": [{
        "trip_id": "68231004-DEC25-D10CAR-1Weekday", "direction_id": 0,
        "sched_start": "2026-11-30T15:12:00Z", "sched_start_local": "07:12",
        "outcome": "missed", "announced": True, "advance_notice_s": 2700.0, "stop_coverage": None,
    }],
    "next_cursor": None,
}  # fmt: skip

# The whole system: its own counts, not one line's (same arithmetic as RATES).
SYSTEM_RATES: dict[str, Any] = {
    "n_scheduled": 251000, "n_unknown": 3000, "n_ran": 231500, "n_partial": 4100,
    "n_missed": 12400, "n_missed_announced": 7100, "n_missed_unplanned": 5300, "n_trips": 248000,
    "n_service_days": 17, "missed_rate": 0.05, "announced_rate": 0.0286,
    "unplanned_rate": 0.0214, "unplanned_share": 0.4274, "missed_rate_ci_low": 0.0462,
    "missed_rate_ci_high": 0.0541, "unplanned_share_ci_low": 0.3988,
    "unplanned_share_ci_high": 0.4561, "suppressed": False,
}  # fmt: skip

SYSTEM_SUMMARY = {
    "data_as_of": AS_OF,
    "windows": [{
        "window": "28d", "window_start": "2026-11-04", "data_through": "2026-12-01",
        "first_data_date": "2026-11-15", "n_lines": 117, "rates": SYSTEM_RATES,
    }],
}  # fmt: skip

FEED_HEALTH = {
    "hours": 24, "data_as_of": AS_OF,
    "buckets": [{
        "feed": "trip_updates", "bucket_start": "2026-12-01T17:35:00Z", "n_fetches": 30,
        "n_success": 30, "n_errors": 0, "error_rate": 0.0, "freshest_age_s": 4.2,
        "healthy": True,
    }],
}  # fmt: skip

METHOD = {
    "data_as_of": AS_OF,
    "thresholds": [{
        "name": "min_cell_trips", "value": "30", "unit": "trips",
        "description": "Fewest trips behind any published rate.",
        "decision": "ADR-025, ADR-026",
    }],
    "outcomes": [{"term": "missed", "meaning": "Not seen while the feeds were healthy."}],
    "rates": [{
        "term": "missed_rate",
        "meaning": "Missed trips divided by scheduled trips minus unknown ones (n_trips).",
    }],
    "notes": ["Ghost Bus LA is not affiliated with LA Metro."],
}  # fmt: skip

CURRENT_CANCELLATIONS = {
    "as_of": "2026-12-01T17:38:00Z", "stale": False, "data_as_of": AS_OF,
    "cancellations": [{
        "service_date": "2026-12-01", "trip_id": "68231044-DEC25-D10CAR-1Weekday",
        "line": "720", "line_slug": "720", "display_name": "720", "direction_id": 0,
        "headsign": "Santa Monica", "sched_start": "2026-12-01T18:30:00Z",
        "sched_start_local": "10:30", "first_seen_at": "2026-12-01T17:20:00Z",
        "advance_notice_s": 4200.0,
    }],
}  # fmt: skip
