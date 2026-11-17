"""Tests for schedule-version validity (pipeline spec, section 4).

Every GTFS ZIP with a new hash is a version. It is valid from the later of its
`feed_start_date` and the date it was first seen, until the day before the next version's
`valid_from`. The version in force for service date D is the one whose range contains D.
"""

import itertools
import random
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from ghostbus_core.schedule_versions import (
    SeenZip,
    resolve_versions,
    version_in_force,
)
from hypothesis import example, given, settings
from hypothesis import strategies as st


def seen(sha: str, first_seen: datetime, start: date | None, end: date | None = None) -> SeenZip:
    return SeenZip(sha256=sha, first_seen_at=first_seen, feed_start_date=start, feed_end_date=end)


def utc(y: int, m: int, d: int, h: int = 12) -> datetime:
    return datetime(y, m, d, h, tzinfo=UTC)


LA = ZoneInfo("America/Los_Angeles")
A, B, C = "a" * 64, "b" * 64, "c" * 64


def test_single_version_is_valid_from_first_seen_with_an_open_end() -> None:
    [v] = resolve_versions([seen(A, utc(2026, 11, 15), date(2026, 6, 1))])
    assert (v.version_id, v.valid_from, v.valid_to) == (A[:16], date(2026, 11, 15), None)


def test_next_version_closes_the_previous_one_the_day_before() -> None:
    versions = resolve_versions(
        [seen(A, utc(2026, 11, 15), date(2026, 6, 1)), seen(B, utc(2026, 11, 22), None)]
    )
    assert [(v.version_id, v.valid_from, v.valid_to) for v in versions] == [
        (A[:16], date(2026, 11, 15), date(2026, 11, 21)),
        (B[:16], date(2026, 11, 22), None),
    ]


def test_a_schedule_published_early_takes_effect_on_its_start_date() -> None:
    # Metro's next schedule is expected on Dec 13 (pipeline spec, section 4). Downloaded on
    # Dec 5, it must not replace the current one until then.
    versions = resolve_versions(
        [
            seen(A, utc(2026, 11, 15), date(2026, 6, 1)),
            seen(B, utc(2026, 12, 5), date(2026, 12, 13)),
        ]
    )
    assert version_in_force(versions, date(2026, 12, 12)) == versions[0]
    assert version_in_force(versions, date(2026, 12, 13)) == versions[1]
    assert versions[0].valid_to == date(2026, 12, 12)


def test_a_weekly_update_of_the_current_schedule_slots_in_before_a_future_one() -> None:
    # Seen order: current (A), future service change (B, from Dec 13), then a weekly
    # calendar_dates update of the current schedule (C, from Dec 8). Validity follows
    # valid_from, not download order.
    versions = resolve_versions(
        [
            seen(A, utc(2026, 11, 15), date(2026, 6, 1)),
            seen(B, utc(2026, 12, 5), date(2026, 12, 13)),
            seen(C, utc(2026, 12, 8), date(2026, 12, 8)),
        ]
    )
    assert [(v.version_id[0], v.valid_from, v.valid_to) for v in versions] == [
        ("a", date(2026, 11, 15), date(2026, 12, 7)),
        ("c", date(2026, 12, 8), date(2026, 12, 12)),
        ("b", date(2026, 12, 13), None),
    ]


def test_the_same_zip_seen_twice_counts_once_from_its_earliest_sighting() -> None:
    # The same ZIP can sit under two dt= partitions (pipeline spec, section 4).
    versions = resolve_versions(
        [seen(A, utc(2026, 11, 16), date(2026, 6, 1)), seen(A, utc(2026, 11, 15), date(2026, 6, 1))]
    )
    assert [(v.version_id, v.first_seen_at) for v in versions] == [(A[:16], utc(2026, 11, 15))]


def test_two_versions_taking_effect_the_same_day_the_later_sighting_wins() -> None:
    # Metro republished twice on one LA day (07:00 and 15:00 PST), or ingest restarted
    # mid-day and fetched a changed ZIP. B wins the day; A keeps a row with an empty range,
    # so rows already matched against A still resolve.
    versions = resolve_versions(
        [seen(A, utc(2026, 11, 15, 15), None), seen(B, utc(2026, 11, 15, 23), None)]
    )
    assert [(v.version_id[0], v.valid_from, v.valid_to, v.ever_in_force) for v in versions] == [
        ("a", date(2026, 11, 15), date(2026, 11, 14), False),
        ("b", date(2026, 11, 15), None, True),
    ]
    in_force = version_in_force(versions, date(2026, 11, 15))
    assert in_force is not None
    assert in_force.version_id == B[:16]


def test_known_limit_a_revert_to_old_bytes_is_not_detected() -> None:
    # Pins the spec's current rule (earliest sighting per hash; SPEC section 10 open
    # question): A, then B, then A's exact bytes again on Nov 25. A keeps its Nov 15 date,
    # so B stays in force. Change this test only together with the spec.
    versions = resolve_versions(
        [
            seen(A, utc(2026, 11, 15), None),
            seen(B, utc(2026, 11, 20), None),
            seen(A, utc(2026, 11, 25), None),
        ]
    )
    in_force = version_in_force(versions, date(2026, 11, 26))
    assert in_force is not None
    assert in_force.version_id == B[:16]


def test_first_seen_date_is_the_los_angeles_date() -> None:
    # 2026-11-16 05:00 UTC is 21:00 PST on Nov 15.
    [v] = resolve_versions([seen(A, datetime(2026, 11, 16, 5, tzinfo=UTC), None)])
    assert v.valid_from == date(2026, 11, 15)


def test_no_version_in_force_before_the_first_one() -> None:
    versions = resolve_versions([seen(A, utc(2026, 11, 15), date(2026, 6, 1))])
    assert version_in_force(versions, date(2026, 11, 14)) is None


def test_feed_dates_are_carried_through() -> None:
    [v] = resolve_versions([seen(A, utc(2026, 11, 15), date(2026, 6, 1), date(2026, 12, 12))])
    assert (v.feed_start_date, v.feed_end_date) == (date(2026, 6, 1), date(2026, 12, 12))


def test_rejects_naive_first_seen() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        resolve_versions([seen(A, datetime(2026, 11, 15), None)])  # noqa: DTZ001


def test_rejects_one_hash_with_two_different_feed_dates() -> None:
    # Identical bytes can't carry two feed_info.txt files: the input is corrupt.
    with pytest.raises(ValueError, match="different feed dates"):
        resolve_versions(
            [seen(A, utc(2026, 11, 15), date(2026, 6, 1)), seen(A, utc(2026, 11, 16), None)]
        )


def test_rejects_a_malformed_hash() -> None:
    with pytest.raises(ValueError, match="sha256"):
        resolve_versions([seen("xyz", utc(2026, 11, 15), None)])


def test_empty_input_has_no_versions() -> None:
    assert resolve_versions([]) == []
    assert version_in_force([], date(2026, 11, 15)) is None


# --- properties ---------------------------------------------------------------------------

day0 = date(2026, 1, 1)
HASHES = [c * 64 for c in "0123456789abcdef"]


def _start_for(sha: str) -> date | None:
    # Same bytes, same feed_info.txt: a hash always carries the same feed dates.
    n = int(sha[0], 16)
    return None if n % 4 == 0 else day0 + timedelta(days=37 * n - 100)


# Any hour, so sightings between 00:00 and 08:00 UTC fall on the previous LA date.
sightings = st.lists(
    st.builds(
        lambda sha, n: seen(sha, datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=n),
                            _start_for(sha)),
        st.sampled_from(HASHES),
        st.integers(0, 400 * 24),
    ),
    max_size=12,
)  # fmt: skip


def oracle(zips: list[SeenZip], day: date) -> str | None:
    """Brute force, written independently of the module: of the hashes (dated from their
    earliest sighting) whose start is on or before the day, the latest start wins, and on a
    tie the latest sighting, then the larger hash."""
    first: dict[str, SeenZip] = {}
    for z in zips:
        if z.sha256 not in first or z.first_seen_at < first[z.sha256].first_seen_at:
            first[z.sha256] = z
    best: tuple[date, datetime, str] | None = None
    for z in first.values():
        seen_on = z.first_seen_at.astimezone(LA).date()
        start = max(seen_on, z.feed_start_date) if z.feed_start_date else seen_on
        key = (start, z.first_seen_at, z.sha256)
        if start <= day and (best is None or key > best):
            best = key
    return best[2][:16] if best else None


@settings(max_examples=500)
@given(sightings, st.integers(-120, 520))
@example(  # 05:00 UTC on Mar 2 is Mar 1 in LA: the oracle must see B in force on Mar 1
    [seen(A, datetime(2026, 2, 1, 20, tzinfo=UTC), None),
     seen(B, datetime(2026, 3, 2, 5, tzinfo=UTC), None)],
    59,
)  # fmt: skip
def test_version_in_force_matches_a_brute_force_oracle(zips: list[SeenZip], offset: int) -> None:
    day = day0 + timedelta(days=offset)
    got = version_in_force(resolve_versions(zips), day)
    assert (got.version_id if got else None) == oracle(zips, day)


@given(sightings)
def test_every_distinct_hash_gets_exactly_one_row(zips: list[SeenZip]) -> None:
    ids = [v.version_id for v in resolve_versions(zips)]
    assert sorted(ids) == sorted({z.sha256[:16] for z in zips})


@given(sightings)
def test_ranges_in_force_are_ordered_contiguous_and_non_overlapping(zips: list[SeenZip]) -> None:
    live = [v for v in resolve_versions(zips) if v.ever_in_force]
    for prev, nxt in itertools.pairwise(live):
        assert prev.valid_to is not None
        assert prev.valid_from <= prev.valid_to
        assert prev.valid_to + timedelta(days=1) == nxt.valid_from
    if live:
        assert live[-1].valid_to is None


@given(sightings, st.integers(-120, 520))
def test_at_most_one_version_covers_a_day_and_one_does_from_the_first(
    zips: list[SeenZip], offset: int
) -> None:
    versions = resolve_versions(zips)
    day = day0 + timedelta(days=offset)
    covering = [v for v in versions if v.covers(day)]
    assert len(covering) <= 1
    if versions and day >= min(v.valid_from for v in versions):
        assert len(covering) == 1


@given(sightings, st.randoms())
def test_input_order_does_not_matter(zips: list[SeenZip], rnd: random.Random) -> None:
    shuffled = list(zips)
    rnd.shuffle(shuffled)
    assert resolve_versions(shuffled) == resolve_versions(zips)
