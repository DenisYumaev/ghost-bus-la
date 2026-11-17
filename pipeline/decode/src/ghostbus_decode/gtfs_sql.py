"""SQL fragments for GTFS values, kept in agreement with `ghostbus_core.service_date`.

Tests run each fragment against the Python reference on the same inputs, so the two
implementations can't drift (pipeline spec, section 5).
"""

import re

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# One or two ASCII hour digits (Metro writes "8:05:09"), minutes and seconds 00-59.
_TIME_RE = r"^([0-9]{1,2}):([0-5][0-9]):([0-5][0-9])$"


# The characters Python's str.strip() removes that GTFS files plausibly contain. DuckDB's
# trim() with no argument removes only spaces.
_STRIP = "' ' || chr(9) || chr(10) || chr(13)"


def trim_sql(column: str) -> str:
    """SQL: the column with surrounding spaces, tabs, CR and LF removed (quoted identifier)."""
    if _IDENT.fullmatch(column) is None:
        raise ValueError(f"not a plain column name: {column!r}")
    return f'trim("{column}", {_STRIP})'


def gtfs_seconds_sql(column: str) -> str:
    """SQL expression: a GTFS time column to seconds since noon minus 12 h, as INTEGER.

    NULL for blank values (allowed between timepoints) and for anything malformed or past
    47:59:59; the loader counts malformed values separately and refuses to load them.
    """
    t = trim_sql(column)

    def part(n: int) -> str:
        # TRY_CAST, not CAST: SQL doesn't promise the WHEN guard is evaluated first.
        return f"TRY_CAST(regexp_extract({t}, '{_TIME_RE}', {n}) AS INTEGER)"

    return (
        f"CASE WHEN regexp_full_match({t}, '{_TIME_RE[1:-1]}') AND {part(1)} < 48 "
        f"THEN {part(1)} * 3600 + {part(2)} * 60 + {part(3)} END"
    )
