"""Which GTFS schedule version is in force on a service date (pipeline spec, section 4).

Metro's `feed_version` is empty, so a version is identified by the ZIP's SHA-256. Each
version is valid from the later of its `feed_start_date` and the Los Angeles date it was
first seen, until the day before the next version's `valid_from`. Ordering is by
`valid_from`, not by download order: a service change published a week early waits for its
start date, and a weekly update of the current schedule seen in the meantime slots in
before it. That ordering, and the rule that a hash is dated from its earliest sighting, are
the spec's; their known limits (a revert to old bytes, a postponed service change) are open
questions in `docs/SPEC.md` section 10.

"Date first seen" is the America/Los_Angeles calendar date of `first_seen_at`, because
`valid_from` is compared with service dates, which are Los Angeles dates (hard rule 5). A
ZIP first seen mid-day replaces that day's version for the whole service date on rebuild.

Trip IDs change at every service change (ADR-001 decision 4), so every join from realtime
data to the schedule resolves through `version_in_force` for that service date.

Pure functions: the loader feeds in what it found in bronze; dbt and the detector read the
result as `dim_schedule_version`.
"""

import itertools
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from ghostbus_core.service_date import AGENCY_TZ

VERSION_ID_LEN = 16  # matches the bronze key's sha16, so a version id points at its object
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class SeenZip:
    """One GTFS ZIP found in bronze. The same hash may appear more than once."""

    sha256: str
    first_seen_at: datetime  # aware; from the fetch log
    feed_start_date: date | None  # from feed_info.txt when present
    feed_end_date: date | None = None


@dataclass(frozen=True)
class ScheduleVersion:
    """A row of `dim_schedule_version`. `valid_to` is None for the newest version."""

    version_id: str
    sha256: str
    first_seen_at: datetime
    feed_start_date: date | None
    feed_end_date: date | None
    valid_from: date
    valid_to: date | None

    @property
    def ever_in_force(self) -> bool:
        """False for a version superseded on the day it would have taken effect."""
        return self.valid_to is None or self.valid_to >= self.valid_from

    def covers(self, service_date: date) -> bool:
        return self.valid_from <= service_date and (
            self.valid_to is None or service_date <= self.valid_to
        )


def resolve_versions(zips: Iterable[SeenZip]) -> list[ScheduleVersion]:
    """One row per distinct hash, ordered by `valid_from`, then by when it was seen.

    When two versions share a `valid_from` (Metro republished on one day; or ingest
    restarted mid-day and fetched a changed ZIP), the one seen last wins that day. The
    loser keeps its row with an empty range (`valid_to` the day before `valid_from`): rows
    already matched against it, such as an alert sent that morning, still resolve to a
    known version, and versions are never deleted (pipeline spec, section 4).
    """
    earliest: dict[str, SeenZip] = {}
    for z in zips:
        _validate(z)
        kept = earliest.get(z.sha256)
        if kept is not None and _feed_dates(kept) != _feed_dates(z):
            raise ValueError(f"{z.sha256[:VERSION_ID_LEN]} seen with different feed dates")
        if kept is None or z.first_seen_at < kept.first_seen_at:
            earliest[z.sha256] = z

    # Ties on first_seen_at break on the hash, so the result never depends on input order.
    ordered = sorted(earliest.values(), key=lambda z: (_valid_from(z), z.first_seen_at, z.sha256))
    winners = {_valid_from(z): z for z in ordered}  # the last per valid_from wins
    starts = sorted(winners)
    next_start = dict(itertools.pairwise(starts))

    versions = []
    for z in ordered:
        start = _valid_from(z)
        if winners[start] is not z:
            end: date | None = start - timedelta(days=1)  # superseded: empty range
        elif start in next_start:
            end = next_start[start] - timedelta(days=1)
        else:
            end = None
        versions.append(
            ScheduleVersion(
                version_id=z.sha256[:VERSION_ID_LEN],
                sha256=z.sha256,
                first_seen_at=z.first_seen_at,
                feed_start_date=z.feed_start_date,
                feed_end_date=z.feed_end_date,
                valid_from=start,
                valid_to=end,
            )
        )
    return versions


def version_in_force(
    versions: Sequence[ScheduleVersion], service_date: date
) -> ScheduleVersion | None:
    """The version whose range contains the date, or None before the first version."""
    for v in versions:
        if v.covers(service_date):
            return v
    return None


def _feed_dates(z: SeenZip) -> tuple[date | None, date | None]:
    return z.feed_start_date, z.feed_end_date


def _valid_from(z: SeenZip) -> date:
    seen_on = z.first_seen_at.astimezone(AGENCY_TZ).date()
    return max(seen_on, z.feed_start_date) if z.feed_start_date else seen_on


def _validate(z: SeenZip) -> None:
    if _SHA256.fullmatch(z.sha256) is None:
        raise ValueError(f"not a lowercase hex sha256: {z.sha256!r}")
    if z.first_seen_at.tzinfo is None or z.first_seen_at.utcoffset() is None:
        raise ValueError("first_seen_at must be timezone-aware")
