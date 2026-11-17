"""The SQL version of GTFS time parsing must agree with ghostbus_core's Python version.

dbt and the loader parse 2.1 million stop times in DuckDB; the Python parser is the reviewed
reference (PR #25). These tests run both on the same inputs.
"""

import duckdb
import pytest
from ghostbus_core.service_date import MAX_GTFS_SECONDS, format_gtfs_time, parse_gtfs_time
from ghostbus_decode.gtfs_sql import gtfs_seconds_sql
from hypothesis import given, settings
from hypothesis import strategies as st


def sql_parse(text: str | None) -> int | None:
    with duckdb.connect() as con:
        query = f"SELECT {gtfs_seconds_sql('t')} FROM (SELECT ?::VARCHAR AS t)"  # noqa: S608
        result = con.execute(query, [text]).fetchall()[0][0]
    return None if result is None else int(result)


def python_parse(text: str) -> int | None:
    try:
        return parse_gtfs_time(text)
    except ValueError:
        return None


@pytest.mark.parametrize(
    ("text", "expected"),
    [("08:50:00", 8 * 3600 + 50 * 60), ("8:05:09", 29109), ("29:45:00", 107100),
     (" 07:30:00 ", 27000), ("24:00:00", 86400)],
)  # fmt: skip
def test_known_times(text: str, expected: int) -> None:
    assert sql_parse(text) == expected


@pytest.mark.parametrize("text", [None, "", "   "])
def test_blank_is_null(text: str | None) -> None:
    # GTFS allows empty arrival/departure times between timepoints.
    assert sql_parse(text) is None


@pytest.mark.parametrize(
    "text", ["7:30", "07:60:00", "aa:bb:cc", "100:00:00", "48:00:00", "٠٨:00:00", "07:00:00Z"]
)
def test_malformed_is_null(text: str) -> None:
    assert sql_parse(text) is None


@settings(max_examples=300)
@given(st.integers(min_value=0, max_value=MAX_GTFS_SECONDS))
def test_agrees_with_python_on_every_valid_time(seconds: int) -> None:
    text = format_gtfs_time(seconds)
    assert sql_parse(text) == parse_gtfs_time(text) == seconds
    if text.startswith("0"):  # Metro also writes hours without the leading zero
        assert sql_parse(text[1:]) == seconds


@settings(max_examples=300)
@given(st.text(alphabet="0123456789: \u0660x", max_size=10))
def test_agrees_with_python_on_arbitrary_text(text: str) -> None:
    expected = None if not text.strip() else python_parse(text)
    assert sql_parse(text) == expected


def test_only_plain_column_names_are_accepted() -> None:
    with pytest.raises(ValueError, match="column name"):
        gtfs_seconds_sql("t); DROP TABLE x; --")
