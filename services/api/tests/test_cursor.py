"""Cursors (API spec sections 3 and 9): opaque, round-trip exactly, refuse garbage."""

from datetime import UTC, datetime, timedelta

import pytest
from ghostbus_api.cursor import BadCursor, decode, encode
from hypothesis import given
from hypothesis import strategies as st

# Hypothesis takes naive bounds and attaches the time zone itself.
starts = st.datetimes(
    min_value=datetime(2020, 1, 1),  # noqa: DTZ001
    max_value=datetime(2035, 1, 1),  # noqa: DTZ001
    timezones=st.just(UTC),
)
trip_ids = st.text(min_size=1, max_size=40)


@given(starts, trip_ids)
def test_a_cursor_round_trips(start: datetime, trip_id: str) -> None:
    assert decode(encode(start, trip_id)) == (start, trip_id)


@given(starts, trip_ids)
def test_a_cursor_is_url_safe(start: datetime, trip_id: str) -> None:
    token = encode(start, trip_id)
    assert all(c.isalnum() or c in "-_" for c in token)


def test_order_of_keys_survives(tmp_path: object) -> None:
    a = datetime(2026, 11, 14, 16, 0, tzinfo=UTC)
    assert decode(encode(a, "T1"))[0] < decode(encode(a + timedelta(minutes=1), "T0"))[0]


@pytest.mark.parametrize("token", ["", "!!!", "bm90IGpzb24", "WzFd", "WyJ4IiwgInkiXQ"])
def test_garbage_is_refused(token: str) -> None:
    with pytest.raises(BadCursor):
        decode(token)
