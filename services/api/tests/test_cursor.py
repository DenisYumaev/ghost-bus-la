"""Cursors (API spec sections 3 and 9): opaque, round-trip exactly, refuse garbage."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from ghostbus_api.cursor import BadCursor, Position, decode, encode
from hypothesis import given
from hypothesis import strategies as st

offsets = st.sampled_from([UTC, timezone(timedelta(hours=-8)), timezone(timedelta(hours=5.5))])
# Hypothesis takes naive bounds and attaches the time zone itself.
positions = st.builds(
    Position,
    line=st.text(min_size=1, max_size=40),
    service_date=st.dates(min_value=date(2020, 1, 1), max_value=date(2035, 1, 1)),
    sched_start=st.datetimes(
        min_value=datetime(2020, 1, 1),  # noqa: DTZ001
        max_value=datetime(2035, 1, 1),  # noqa: DTZ001
        timezones=offsets,
    ),
    trip_id=st.text(min_size=1, max_size=40),
)


@given(positions)
def test_a_cursor_round_trips(pos: Position) -> None:
    assert decode(encode(pos)) == pos


@given(positions)
def test_a_cursor_is_url_safe(pos: Position) -> None:
    assert all(c.isalnum() or c in "-_" for c in encode(pos))


@pytest.mark.parametrize(
    "token",
    [
        "",
        "!!!",
        "bm90IGpzb24",  # not JSON
        "WzFd",  # [1]
        "WyJ4IiwgInkiXQ",  # ["x", "y"]
        # A naive start time: not one we issue.
        encode(Position("2", date(2026, 11, 14), datetime(2026, 11, 14, 16), "T1")),  # noqa: DTZ001
    ],
)
def test_garbage_is_refused(token: str) -> None:
    with pytest.raises(BadCursor):
        decode(token)
