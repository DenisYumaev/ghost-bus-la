"""Tests for ghostbus_ingest.backoff: exponential delay, capped, with jitter (spec 2.3)."""

import pytest
from ghostbus_ingest.backoff import backoff_delay
from hypothesis import given
from hypothesis import strategies as st


@pytest.mark.parametrize(
    ("attempt", "expected"), [(0, 1.0), (1, 2.0), (2, 4.0), (5, 32.0), (6, 60.0), (40, 60.0)]
)
def test_doubles_from_one_second_and_caps_at_sixty(attempt: int, expected: float) -> None:
    # With jitter pinned to its maximum, the delay is exactly the schedule 1, 2, 4, ... 60.
    assert backoff_delay(attempt, rand=lambda: 1.0) == expected


def test_jitter_spreads_each_delay_between_half_and_full() -> None:
    assert backoff_delay(3, rand=lambda: 0.0) == 4.0
    assert backoff_delay(3, rand=lambda: 0.5) == 6.0


@given(attempt=st.integers(min_value=0, max_value=10_000), r=st.floats(min_value=0, max_value=1))
def test_delay_is_always_positive_and_never_above_the_cap(attempt: int, r: float) -> None:
    delay = backoff_delay(attempt, rand=lambda: r)
    assert 0.5 <= delay <= 60.0


def test_negative_attempts_are_rejected() -> None:
    with pytest.raises(ValueError, match="attempt"):
        backoff_delay(-1)
