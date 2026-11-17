"""GTFS time and service-date math (pipeline spec, section 5; learning spec, piece 1).

A GTFS stop time such as `25:10:00` is not a clock reading. It counts elapsed seconds from
"noon minus 12 hours" on the service date, in the agency's time zone. On most days that
reference is local midnight. On the two days a year when the clocks change it is not:
noon minus 12 hours is 23:00 the evening before on the spring-forward day, and 01:00 on the
fall-back day. Anchoring on noon keeps every time after the 02:00 switch equal to its
wall-clock reading, and makes differences between GTFS times real elapsed seconds.

So the conversion is: find local noon on the service date, convert that instant to UTC,
subtract 12 hours, add the GTFS seconds. All arithmetic after the first step happens in UTC,
where hours have no gaps or repeats.

Everything here is pure and timezone-aware: datetimes in and out are aware UTC instants.

Needs the system time zone database (zoneinfo), which the Debian-based images and CI runners
have; the ingest image's smoke test already asserts it. Bundling `tzdata` instead would be a
new dependency (CLAUDE.md: ADR first).
"""

import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

AGENCY_TZ = ZoneInfo("America/Los_Angeles")

# GTFS allows times past 24:00 for trips that run after midnight. Metro's latest is 29:45
# (pipeline spec, section 4); two full days is a generous ceiling that still catches garbage.
MAX_GTFS_SECONDS = 48 * 3600 - 1

# One or two hour digits: Metro writes some hours without a leading zero ("8:05:09").
_GTFS_TIME = re.compile(r"([0-9]{1,2}):([0-5][0-9]):([0-5][0-9])")
_SERVICE_DATE = re.compile(r"[0-9]{8}")  # [0-9], not \d, which matches any Unicode digit
_HALF_DAY = timedelta(hours=12)
_SECOND = timedelta(seconds=1)


def parse_gtfs_time(text: str) -> int:
    """`H:MM:SS` or `HH:MM:SS`, possibly past 24:00, to seconds since the reference."""
    match = _GTFS_TIME.fullmatch(text.strip())
    if match is None:
        raise ValueError(f"not a GTFS time: {text!r}")
    hours, minutes, seconds = (int(g) for g in match.groups())
    total = hours * 3600 + minutes * 60 + seconds
    if total > MAX_GTFS_SECONDS:
        raise ValueError(f"GTFS time out of range: {text!r}")
    return total


def format_gtfs_time(seconds: int) -> str:
    """Seconds since the reference to `HH:MM:SS`; hours run past 24 rather than wrapping."""
    _check_range(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def parse_service_date(text: str) -> date:
    """A GTFS-rt `start_date` (`YYYYMMDD`) to a date."""
    if _SERVICE_DATE.fullmatch(text) is None:
        raise ValueError(f"not a YYYYMMDD service date: {text!r}")
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:]))
    except ValueError as exc:
        raise ValueError(f"not a valid service date: {text!r}") from exc


def to_utc(service_date: date, seconds: int, tz: ZoneInfo = AGENCY_TZ) -> datetime:
    """The UTC instant of a GTFS time on a service date."""
    _check_range(seconds)
    return _reference(service_date, tz) + timedelta(seconds=seconds)


def from_utc(service_date: date, at: datetime, tz: ZoneInfo = AGENCY_TZ) -> int:
    """Seconds from the service date's reference to an aware instant: the inverse of to_utc.

    The result may be negative or past MAX_GTFS_SECONDS if `at` is far from that service
    date; callers comparing observations to a schedule want the raw offset.
    """
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("from_utc needs a timezone-aware datetime")
    # Floor division, not int(): int() truncates toward zero, so 0.5 s before the reference
    # would read as 0, the same second as the reference itself.
    return (at.astimezone(UTC) - _reference(service_date, tz)) // _SECOND


def _reference(service_date: date, tz: ZoneInfo) -> datetime:
    """Noon minus 12 hours: local noon as a UTC instant, then 12 real hours earlier."""
    noon = datetime.combine(service_date, time(12), tzinfo=tz)
    return noon.astimezone(UTC) - _HALF_DAY


def _check_range(seconds: int) -> None:
    if not 0 <= seconds <= MAX_GTFS_SECONDS:
        raise ValueError(f"GTFS time out of range: {seconds} s")
