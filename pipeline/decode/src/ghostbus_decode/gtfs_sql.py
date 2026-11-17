"""SQL fragments for GTFS values, kept in agreement with `ghostbus_core.service_date`.

Tests run each fragment against the Python reference on the same inputs, so the two
implementations can't drift (pipeline spec, section 5).
"""

import re

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# One or two ASCII hour digits (Metro writes "8:05:09"), minutes and seconds 00-59.
_TIME_RE = r"^([0-9]{1,2}):([0-5][0-9]):([0-5][0-9])$"


def gtfs_seconds_sql(column: str) -> str:
    """SQL expression: a GTFS time column to seconds since noon minus 12 h, as INTEGER.

    NULL for blank values (allowed between timepoints) and for anything malformed or past
    47:59:59; the loader counts malformed values separately and refuses to load them.
    """
    if _IDENT.fullmatch(column) is None:
        raise ValueError(f"not a plain column name: {column!r}")
    t = f"trim({column})"
    seconds = (
        f"CAST(regexp_extract({t}, '{_TIME_RE}', 1) AS INTEGER) * 3600 + "
        f"CAST(regexp_extract({t}, '{_TIME_RE}', 2) AS INTEGER) * 60 + "
        f"CAST(regexp_extract({t}, '{_TIME_RE}', 3) AS INTEGER)"
    )
    return (
        f"CASE WHEN regexp_full_match({t}, '{_TIME_RE[1:-1]}') "
        f"AND CAST(regexp_extract({t}, '{_TIME_RE}', 1) AS INTEGER) < 48 "
        f"THEN {seconds} END"
    )
