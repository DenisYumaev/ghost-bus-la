"""Tests for GTFS time and service-date math (pipeline spec, section 5).

Hand-checked fixtures cover the cases the spec names: a trip past 24:00, the March 2027
spring-forward date, a fall-back date, and a trip that spans midnight UTC. Hypothesis checks
the properties that must hold on every date, including dates nobody thought to test.
"""

import csv
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from ghostbus_core.service_date import (
    MAX_GTFS_SECONDS,
    format_gtfs_time,
    from_utc,
    parse_gtfs_time,
    parse_service_date,
    to_utc,
)
from hypothesis import given
from hypothesis import strategies as st

LA = ZoneInfo("America/Los_Angeles")


def utc(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


# --- parsing -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("00:00:00", 0),
        ("08:05:09", 8 * 3600 + 5 * 60 + 9),
        ("8:05:09", 8 * 3600 + 5 * 60 + 9),  # Metro: some hours lack a leading zero
        ("24:00:00", 24 * 3600),
        ("25:10:00", 25 * 3600 + 10 * 60),
        ("29:45:00", 29 * 3600 + 45 * 60),  # Metro's latest time (pipeline spec, section 4)
        (" 07:30:00 ", 7 * 3600 + 30 * 60),  # CSV padding
    ],
)
def test_parse_gtfs_time(text: str, seconds: int) -> None:
    assert parse_gtfs_time(text) == seconds


@pytest.mark.parametrize(
    "text",
    ["", "7:30", "07:60:00", "07:00:60", "-1:00:00", "07:3:00", "aa:bb:cc", "100:00:00",
     "48:00:00", "07:00:00.5", "07:00:00Z", "\u0660\u0668:00:00"],
)  # fmt: skip
def test_parse_gtfs_time_rejects_malformed_text(text: str) -> None:
    with pytest.raises(ValueError, match="GTFS time"):
        parse_gtfs_time(text)


def test_format_pads_hours_and_keeps_hours_past_24() -> None:
    assert format_gtfs_time(25 * 3600 + 10 * 60) == "25:10:00"
    assert format_gtfs_time(8 * 3600 + 5) == "08:00:05"


@pytest.mark.parametrize("seconds", [-1, MAX_GTFS_SECONDS + 1])
def test_format_rejects_out_of_range(seconds: int) -> None:
    with pytest.raises(ValueError, match="GTFS time"):
        format_gtfs_time(seconds)


@given(st.integers(min_value=0, max_value=MAX_GTFS_SECONDS))
def test_format_then_parse_round_trips(seconds: int) -> None:
    assert parse_gtfs_time(format_gtfs_time(seconds)) == seconds


def test_parse_service_date_reads_the_realtime_start_date() -> None:
    # GTFS-rt trip descriptors carry start_date as YYYYMMDD.
    assert parse_service_date("20261113") == date(2026, 11, 13)


@pytest.mark.parametrize(
    "text", ["2026-11-13", "2026111", "20261332", "", "2026111a", "2026111\u0663"]
)
def test_parse_service_date_rejects_other_formats(text: str) -> None:
    with pytest.raises(ValueError, match="service date"):
        parse_service_date(text)


# --- hand-checked conversions --------------------------------------------------------------

# Shared with the dbt unit tests, so the SQL version of this rule is pinned to the same values.
# Includes the cases where "noon minus 12 h" differs from a wall clock: times before 03:00 on a
# clock-change day, and owl trips past 24:00 on the evening before one.
CASES = Path(__file__).parents[3] / "tests" / "fixtures" / "gtfs_time_cases.csv"


def load_cases() -> list[tuple[date, str, datetime, str]]:
    with CASES.open(newline="") as f:
        return [
            (date.fromisoformat(r["service_date"]), r["gtfs_time"],
             datetime.fromisoformat(r["expected_utc"]), r["why"])
            for r in csv.DictReader(f)
        ]  # fmt: skip


@pytest.mark.parametrize(("day", "text", "expected", "why"), load_cases())
def test_hand_checked_cases(day: date, text: str, expected: datetime, why: str) -> None:
    seconds = parse_gtfs_time(text)
    assert to_utc(day, seconds) == expected, why
    assert from_utc(day, expected) == seconds, why


def test_trip_past_24_runs_the_next_local_morning() -> None:
    at = to_utc(date(2026, 11, 13), parse_gtfs_time("25:10:00"))
    assert at.astimezone(LA).replace(tzinfo=None) == datetime(2026, 11, 14, 1, 10)  # noqa: DTZ001


def test_spring_forward_trip_across_the_switch_takes_real_elapsed_time() -> None:
    # Scheduled 01:30 to 03:30 on spring-forward day: two hours of driving, although the wall
    # clock moves three hours (00:30 PST to 03:30 PDT).
    day = date(2027, 3, 14)
    start, end = (to_utc(day, parse_gtfs_time(t)) for t in ("01:30:00", "03:30:00"))
    assert end - start == timedelta(hours=2)


def test_trip_spanning_midnight_utc() -> None:
    # 16:30 to 17:30 PST on 2026-11-16 is 00:30 to 01:30 UTC on Nov 17: the UTC date changes,
    # the service date doesn't.
    day = date(2026, 11, 16)
    start = to_utc(day, parse_gtfs_time("16:30:00"))
    end = to_utc(day, parse_gtfs_time("17:30:00"))
    assert (start, end) == (utc(2026, 11, 17, 0, 30), utc(2026, 11, 17, 1, 30))
    assert from_utc(day, start) == parse_gtfs_time("16:30:00")


def test_to_utc_returns_an_aware_utc_datetime() -> None:
    at = to_utc(date(2026, 7, 4), 0)
    assert at.tzinfo is UTC


def test_from_utc_floors_fractional_seconds() -> None:
    # Half a second before the reference is second -1, not 0: offsets stay monotonic.
    day = date(2026, 7, 4)
    assert from_utc(day, to_utc(day, 0) - timedelta(milliseconds=500)) == -1
    assert from_utc(day, to_utc(day, 0) + timedelta(milliseconds=500)) == 0


def test_from_utc_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        from_utc(date(2026, 7, 4), datetime(2026, 7, 4, 12))  # noqa: DTZ001


def test_to_utc_rejects_out_of_range_seconds() -> None:
    with pytest.raises(ValueError, match="GTFS time"):
        to_utc(date(2026, 7, 4), -1)


# --- properties on every date ---------------------------------------------------------------


def _sundays(year: int, month: int) -> list[date]:
    first = date(year, month, 1)
    first_sunday = first + timedelta(days=(6 - first.weekday()) % 7)
    return [first_sunday + timedelta(weeks=w) for w in range(4)]


def _switch_days(year: int) -> list[date]:
    """US clock-change Sundays (Energy Policy Act rules from 2007), plus the day before each,
    which carries the owl trips that run across the switch."""
    days = [_sundays(year, 3)[1], _sundays(year, 11)[0]]
    return days + [d - timedelta(days=1) for d in days]


# Uniform dates hit a clock-change day about 2 times in 365, so mix them in explicitly.
dst_dates = st.integers(min_value=2007, max_value=2099).flatmap(
    lambda y: st.sampled_from(_switch_days(y))
)
service_dates = st.one_of(
    st.dates(min_value=date(2000, 1, 1), max_value=date(2099, 12, 31)), dst_dates
)


@given(dst_dates)
def test_switch_day_strategy_really_hits_clock_changes(day: date) -> None:
    # Guards the strategy itself: the UTC offset at local noon changes between the day
    # before and the day after, so the clock changed on this day or the next.
    offsets = {
        datetime.combine(d, time(12), tzinfo=LA).utcoffset()
        for d in (day - timedelta(days=1), day, day + timedelta(days=1))
    }
    assert len(offsets) == 2


gtfs_seconds = st.integers(min_value=0, max_value=MAX_GTFS_SECONDS)


@given(service_dates, gtfs_seconds)
def test_from_utc_inverts_to_utc(day: date, seconds: int) -> None:
    assert from_utc(day, to_utc(day, seconds)) == seconds


@given(service_dates, gtfs_seconds, gtfs_seconds)
def test_gtfs_seconds_are_elapsed_seconds(day: date, a: int, b: int) -> None:
    # Differences in GTFS time are real elapsed time, even across a clock change: a trip
    # scheduled 01:30 to 03:30 on spring-forward day takes 2 hours, not 1.
    assert to_utc(day, b) - to_utc(day, a) == timedelta(seconds=b - a)


@given(service_dates)
def test_noon_is_always_local_noon(day: date) -> None:
    # The anchor of the definition: 12:00:00 is noon local time on the service date, on every
    # day of the year, DST or not.
    local = to_utc(day, 12 * 3600).astimezone(LA)
    assert (local.date(), local.hour, local.minute, local.second) == (day, 12, 0, 0)


@given(service_dates, st.integers(min_value=3 * 3600, max_value=24 * 3600 - 1))
def test_daytime_matches_the_local_wall_clock(day: date, seconds: int) -> None:
    # From 03:00 onwards (after any DST switch, which happens at 02:00) GTFS time is the
    # local wall-clock time on the service date.
    local = to_utc(day, seconds).astimezone(LA)
    wall = local.hour * 3600 + local.minute * 60 + local.second
    assert (local.date(), wall) == (day, seconds)
