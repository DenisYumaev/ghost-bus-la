"""Tests for ghostbus_ingest.snapshot: buffering, cutting, completeness, determinism.

All time is passed in explicitly (a fake clock), so nothing here sleeps or touches the network.
Spec: docs/spec/01-data-pipeline.md sections 2.3 and 2.4; ADR-021 decisions 2 and 4.
"""

import base64
import gzip
import hashlib
import json
from pathlib import Path

import pytest
from ghostbus_ingest.snapshot import (
    EmptyCut,
    Snapshot,
    SnapshotBuffer,
    entity_key,
    next_grid_point,
)
from hypothesis import given
from hypothesis import strategies as st

FIXTURES = Path(__file__).parent / "fixtures"


def msg(entity: str, value: int = 0, ts: int = 1_794_457_037) -> bytes:
    return json.dumps({"id": entity, "vehicle": {"timestamp": str(ts), "v": value}}).encode()


def connected_buffer(interval: int = 30, start: float = 990.0) -> SnapshotBuffer:
    """A buffer whose connection has been up since the start of the current grid interval."""
    buf = SnapshotBuffer("vehicle_positions", interval, interval_start=start)
    buf.on_connect(start)
    return buf


# --- the grid ------------------------------------------------------------------------------------


@given(now=st.floats(min_value=0, max_value=4e9), interval=st.sampled_from([30, 60]))
def test_next_grid_point_is_the_next_multiple_of_the_interval(now: float, interval: int) -> None:
    point = next_grid_point(now, interval)
    assert point > now
    assert point - now <= interval
    assert point % interval == 0


def test_a_cut_exactly_on_the_grid_schedules_the_following_point() -> None:
    assert next_grid_point(1020.0, 30) == 1050.0


def test_grid_does_not_drift_when_cuts_run_late() -> None:
    # Each cut finishes 0.7 s late; the schedule must stay on multiples of 30, not creep.
    point, points = 990.0, []
    for _ in range(100):
        point = next_grid_point(point + 0.7, 30)
        points.append(point)
    assert points == [1020.0 + 30 * i for i in range(100)]


# --- entity keys ---------------------------------------------------------------------------------


def test_entity_key_reads_id_and_newest_timestamp() -> None:
    key, ts, keyed = entity_key(msg("9504", ts=1_794_457_037))
    assert (key, ts, keyed) == ("9504", 1_794_457_037, True)


def test_entity_key_reads_trip_update_timestamp() -> None:
    raw = json.dumps({"id": "t1", "tripUpdate": {"timestamp": "1794457342"}}).encode()
    assert entity_key(raw) == ("t1", 1_794_457_342, True)


@pytest.mark.parametrize("raw", [b"not json", b'{"type": "heartbeat"}', b"[1, 2]", b"\xff\xfe"])
def test_frames_without_an_id_get_a_collision_free_synthetic_key(raw: bytes) -> None:
    key, ts, keyed = entity_key(raw)
    assert key == "_noid:" + hashlib.sha256(raw).hexdigest()
    assert ts is None
    assert keyed is False


# --- cutting -------------------------------------------------------------------------------------


def test_latest_message_per_entity_wins() -> None:
    buf = connected_buffer()
    buf.on_message(msg("a", 1), 991.0)
    buf.on_message(msg("b", 1), 992.0)
    buf.on_message(msg("a", 2), 993.0)

    snap = buf.cut(1020.0)

    assert isinstance(snap, Snapshot)
    assert snap.data == msg("a", 2) + b"\n" + msg("b", 1) + b"\n"
    assert (snap.n_entities, snap.n_messages) == (2, 3)


def test_lines_are_the_received_bytes_unchanged_and_sorted_by_entity() -> None:
    raws = [msg("10212", 1), msg("9504", 2), msg("1", 3)]
    buf = connected_buffer()
    for i, raw in enumerate(raws):
        buf.on_message(raw, 991.0 + i)

    snap = buf.cut(1020.0)

    assert isinstance(snap, Snapshot)
    # String order, not numeric: "1" < "10212" < "9504". Stable and simple.
    assert snap.data.splitlines() == [raws[2], raws[0], raws[1]]


@given(
    entities=st.lists(st.text(min_size=1, max_size=8), min_size=1, max_size=30, unique=True),
    seed=st.randoms(use_true_random=False),
)
def test_same_messages_in_any_order_give_identical_bytes_hash_and_gzip(
    entities: list[str], seed: object
) -> None:
    raws = [msg(e, i) for i, e in enumerate(entities)]
    shuffled = list(raws)
    seed.shuffle(shuffled)  # type: ignore[attr-defined]

    snaps = []
    for order in (raws, shuffled):
        buf = connected_buffer()
        for i, raw in enumerate(order):
            buf.on_message(raw, 991.0 + i * 0.001)
        snap = buf.cut(1020.0)
        assert isinstance(snap, Snapshot)
        snaps.append(snap)

    assert snaps[0].data == snaps[1].data
    assert snaps[0].sha256 == snaps[1].sha256
    assert snaps[0].gz == snaps[1].gz


def test_hash_is_of_the_uncompressed_bytes_and_gzip_round_trips() -> None:
    buf = connected_buffer()
    buf.on_message(msg("a"), 991.0)
    snap = buf.cut(1020.0)

    assert isinstance(snap, Snapshot)
    assert snap.sha256 == hashlib.sha256(snap.data).hexdigest()
    assert snap.sha16 == snap.sha256[:16]
    assert gzip.decompress(snap.gz) == snap.data
    assert snap.gz[4:8] == b"\x00\x00\x00\x00", "gzip mtime must be zero for reproducible files"


def test_entities_not_seen_since_the_last_cut_are_absent() -> None:
    buf = connected_buffer()
    buf.on_message(msg("a"), 991.0)
    buf.on_message(msg("b"), 992.0)
    buf.cut(1020.0)
    buf.on_message(msg("a", 9), 1021.0)

    snap = buf.cut(1050.0)

    assert isinstance(snap, Snapshot)
    assert snap.data == msg("a", 9) + b"\n"


def test_newest_entity_timestamp_is_the_maximum_seen() -> None:
    buf = connected_buffer()
    buf.on_message(msg("a", ts=100), 991.0)
    buf.on_message(msg("b", ts=300), 992.0)
    buf.on_message(msg("c", ts=200), 993.0)
    snap = buf.cut(1020.0)

    assert isinstance(snap, Snapshot)
    assert snap.newest_entity_ts == 300


def test_unkeyed_frames_are_stored_and_counted_never_dropped() -> None:
    buf = connected_buffer()
    buf.on_message(b'{"type": "heartbeat"}', 991.0)
    buf.on_message(b'{"type": "heartbeat"}', 992.0)  # identical bytes collapse to one line
    buf.on_message(b"garbage", 993.0)
    buf.on_message(msg("a"), 994.0)

    snap = buf.cut(1020.0)

    assert isinstance(snap, Snapshot)
    assert snap.n_unkeyed == 3
    assert snap.n_entities == 3
    assert b'{"type": "heartbeat"}\n' in snap.data
    assert b"garbage\n" in snap.data


def test_a_frame_containing_a_newline_is_wrapped_reversibly_on_one_line() -> None:
    raw = b'{"id": "x",\n "note": "pretty-printed"}'
    buf = connected_buffer()
    buf.on_message(raw, 991.0)

    snap = buf.cut(1020.0)

    assert isinstance(snap, Snapshot)
    [line] = snap.data.splitlines()
    assert base64.b64decode(json.loads(line)["_unframed_b64"]) == raw
    assert snap.n_unframed == 1


# --- completeness (ADR-021 decision 4) -----------------------------------------------------------


def test_connected_for_the_whole_interval_is_complete() -> None:
    buf = connected_buffer(interval=60, start=960.0)
    buf.on_message(msg("a"), 961.0)

    snap = buf.cut(1020.0)

    assert isinstance(snap, Snapshot)
    assert snap.partial is False
    assert snap.connected_s == pytest.approx(60.0)


def test_a_drop_inside_the_interval_is_partial_and_counts_connected_seconds() -> None:
    # Quiz 001, question 4: down from 08:00:10 to 08:00:50 inside a 60 s interval.
    buf = connected_buffer(interval=60, start=960.0)
    buf.on_message(msg("a"), 965.0)
    buf.on_disconnect(970.0)
    buf.on_connect(1010.0)
    buf.on_message(msg("b"), 1011.0)

    snap = buf.cut(1020.0)

    assert isinstance(snap, Snapshot)
    assert snap.partial is True
    assert snap.connected_s == pytest.approx(20.0)
    assert snap.n_entities == 2


def test_down_for_the_whole_interval_writes_nothing() -> None:
    buf = connected_buffer(interval=30, start=990.0)
    buf.on_message(msg("a"), 991.0)
    buf.cut(1020.0)
    buf.on_disconnect(1020.0)

    cut = buf.cut(1050.0)

    assert isinstance(cut, EmptyCut)
    assert cut.reason == "disconnected"
    assert cut.connected_s == 0


def test_connected_but_silent_writes_nothing() -> None:
    buf = connected_buffer()

    cut = buf.cut(1020.0)

    assert isinstance(cut, EmptyCut)
    assert cut.reason == "no_messages"
    assert cut.connected_s == pytest.approx(30.0)


def test_a_connection_still_down_carries_into_the_next_interval() -> None:
    buf = connected_buffer(interval=30, start=990.0)
    buf.on_disconnect(1000.0)
    buf.cut(1020.0)
    buf.on_connect(1035.0)
    buf.on_message(msg("a"), 1036.0)

    snap = buf.cut(1050.0)

    assert isinstance(snap, Snapshot)
    assert snap.connected_s == pytest.approx(15.0)
    assert snap.partial is True


def test_cut_metadata() -> None:
    buf = connected_buffer()
    buf.on_message(msg("a"), 991.0)
    snap = buf.cut(1020.0)

    assert isinstance(snap, Snapshot)
    assert (snap.feed, snap.cut_at, snap.interval_s) == ("vehicle_positions", 1020.0, 30)


def test_cut_before_the_interval_starts_is_rejected() -> None:
    buf = connected_buffer(start=990.0)
    with pytest.raises(ValueError, match="before"):
        buf.cut(980.0)


# --- real recorded data --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "feed"),
    [
        ("vehicle_positions_45s.jsonl.gz", "vehicle_positions"),
        ("trip_updates_45s.jsonl.gz", "trip_updates"),
    ],
)
def test_replayed_recording_gives_a_partial_then_a_complete_snapshot(name: str, feed: str) -> None:
    with gzip.open(FIXTURES / name, "rt") as f:
        frames = [(rec["t"], rec["raw"].encode()) for rec in map(json.loads, f)]
    all_entities = {entity_key(raw)[0] for _, raw in frames}

    # Connect at 1010.0, 20 s into the grid interval [990, 1020), and replay with real timing.
    # The recording is 45 s long, so the full interval [1020, 1050) lies inside it.
    buf = SnapshotBuffer(feed, 30, interval_start=990.0)
    buf.on_connect(1010.0)
    cuts = []
    next_cut = 1020.0
    for t, raw in frames:
        while 1010.0 + t >= next_cut:
            cuts.append(buf.cut(next_cut))
            next_cut += 30
        buf.on_message(raw, 1010.0 + t)

    first, second = cuts[0], cuts[1]
    assert isinstance(first, Snapshot)
    assert isinstance(second, Snapshot)
    assert first.partial is True
    assert first.connected_s == pytest.approx(10.0)
    assert second.partial is False
    # The completeness rule, on real data: one uninterrupted 30 s interval sees every entity
    # that was in the stream at its start (late joiners may add more).
    assert second.n_entities >= len(all_entities) - 2
