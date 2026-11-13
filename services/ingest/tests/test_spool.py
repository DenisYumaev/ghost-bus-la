"""Tests for the local spool and the fetch log (pipeline spec, sections 2.4 and 2.5).

The spool is where every snapshot lands first, so S3 being down never loses data. These tests
cover the atomic write (a crash never leaves a visible half-written file), the local duplicate
shortcut, naming, and the records the uploader and pipeline depend on.
"""

import gzip
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from ghostbus_ingest.fetch_log import FetchLog
from ghostbus_ingest.snapshot import EmptyCut, Snapshot, SnapshotBuffer
from ghostbus_ingest.spool import Spool, object_key, spool_name

# 2026-11-13T02:14:30Z
CUT_AT = datetime(2026, 11, 13, 2, 14, 30, tzinfo=UTC).timestamp()


def make_snapshot(
    entities: dict[str, int], cut_at: float = CUT_AT, feed: str = "vehicle_positions"
) -> Snapshot:
    buf = SnapshotBuffer(feed, 30, interval_start=cut_at - 30)
    buf.on_connect(cut_at - 30)
    for entity, value in entities.items():
        raw = json.dumps({"id": entity, "vehicle": {"timestamp": "1794536051", "v": value}})
        buf.on_message(raw.encode(), cut_at - 10)
    snap = buf.cut(cut_at)
    assert isinstance(snap, Snapshot)
    return snap


# --- naming --------------------------------------------------------------------------------------


def test_spool_name_carries_fetch_time_and_hash_prefix() -> None:
    snap = make_snapshot({"a": 1})
    assert spool_name(snap) == f"20261113T021430Z_{snap.sha16}.ndjson.gz"


def test_object_key_is_content_addressed_under_the_utc_fetch_date() -> None:
    snap = make_snapshot({"a": 1})
    assert object_key(snap) == f"bronze/vehicle_positions/dt=2026-11-13/{snap.sha16}.ndjson.gz"


@pytest.mark.parametrize(
    ("when", "date"),
    [
        (datetime(2026, 11, 13, 23, 59, 30, tzinfo=UTC), "2026-11-13"),
        (datetime(2026, 11, 14, 0, 0, 0, tzinfo=UTC), "2026-11-14"),
    ],
)
def test_partition_date_is_utc_not_los_angeles(when: datetime, date: str) -> None:
    # 23:59:30 UTC is 15:59:30 in LA; the storage partition is the UTC date (ADR-001 decision 6).
    snap = make_snapshot({"a": 1}, cut_at=when.timestamp())
    assert f"/dt={date}/" in object_key(snap)


# --- writing -------------------------------------------------------------------------------------


def test_write_stores_the_exact_gzip_bytes_and_leaves_no_temp_file(tmp_path: Path) -> None:
    spool = Spool(tmp_path)
    snap = make_snapshot({"a": 1, "b": 2})

    result = spool.write_snapshot(snap)

    assert result.outcome == "written"
    assert result.path == tmp_path / "vehicle_positions" / spool_name(snap)
    assert result.path.read_bytes() == snap.gz
    assert gzip.decompress(result.path.read_bytes()) == snap.data
    assert list((tmp_path / "vehicle_positions").glob("*.tmp")) == []


def test_write_fsyncs_the_file_and_its_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    real_fsync = os.fsync

    def counting_fsync(fd: int) -> None:
        calls.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", counting_fsync)

    Spool(tmp_path).write_snapshot(make_snapshot({"a": 1}))

    assert len(calls) >= 2, "fsync the file before rename, and the directory after"


def test_identical_consecutive_snapshot_is_a_duplicate_and_stores_nothing(tmp_path: Path) -> None:
    spool = Spool(tmp_path)
    first = make_snapshot({"a": 1})
    same_content_later = make_snapshot({"a": 1}, cut_at=CUT_AT + 30)

    spool.write_snapshot(first)
    result = spool.write_snapshot(same_content_later)

    assert result.outcome == "duplicate"
    assert result.path is None
    assert len(list((tmp_path / "vehicle_positions").iterdir())) == 1


def test_shortcut_compares_only_with_the_previous_snapshot_of_the_same_feed(
    tmp_path: Path,
) -> None:
    spool = Spool(tmp_path)
    a1 = make_snapshot({"a": 1})
    b = make_snapshot({"a": 2}, cut_at=CUT_AT + 30)
    a2 = make_snapshot({"a": 1}, cut_at=CUT_AT + 60)
    other_feed_same_bytes = make_snapshot({"a": 1}, cut_at=CUT_AT + 60, feed="trip_updates")

    outcomes = [spool.write_snapshot(s).outcome for s in (a1, b, a2, other_feed_same_bytes)]

    # a2 repeats a1's bytes, but S3, not the shortcut, is the authority for older content.
    assert outcomes == ["written", "written", "written", "written"]


def test_rewriting_after_a_restart_is_idempotent(tmp_path: Path) -> None:
    snap = make_snapshot({"a": 1})
    Spool(tmp_path).write_snapshot(snap)
    result = Spool(tmp_path).write_snapshot(snap)  # a fresh process has no shortcut memory

    assert result.outcome == "written"
    assert [p.name for p in (tmp_path / "vehicle_positions").iterdir()] == [spool_name(snap)]


def test_a_crash_between_write_and_rename_leaves_no_visible_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spool = Spool(tmp_path)

    def crash(src: object, dst: object) -> None:
        raise OSError("simulated crash before rename")

    monkeypatch.setattr(os, "replace", crash)
    with pytest.raises(OSError, match="simulated crash"):
        spool.write_snapshot(make_snapshot({"a": 1}))
    monkeypatch.undo()

    assert spool.pending() == []  # the uploader never sees a half-written file
    assert len(list((tmp_path / "vehicle_positions").glob("*.tmp"))) == 1


def test_a_failed_write_does_not_poison_the_duplicate_shortcut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spool = Spool(tmp_path)
    snap = make_snapshot({"a": 1})
    monkeypatch.setattr(os, "replace", lambda s, d: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        spool.write_snapshot(snap)
    monkeypatch.undo()

    # The same content must be written now, not skipped as a "duplicate" of a failed write.
    assert spool.write_snapshot(snap).outcome == "written"


def test_stale_temp_files_are_removed(tmp_path: Path) -> None:
    spool = Spool(tmp_path)
    feed_dir = tmp_path / "vehicle_positions"
    feed_dir.mkdir()
    old = feed_dir / "20261113T000000Z_aaaa.ndjson.gz.tmp"
    old.write_bytes(b"partial")
    os.utime(old, (CUT_AT - 7200, CUT_AT - 7200))
    fresh = feed_dir / "20261113T021400Z_bbbb.ndjson.gz.tmp"
    fresh.write_bytes(b"in progress")
    os.utime(fresh, (CUT_AT - 5, CUT_AT - 5))

    removed = spool.remove_stale_tmp(now=CUT_AT, older_than_s=3600)

    assert removed == 1
    assert not old.exists()
    assert fresh.exists()


def test_unknown_feed_names_are_rejected(tmp_path: Path) -> None:
    snap = make_snapshot({"a": 1}, feed="../../etc")
    with pytest.raises(ValueError, match="feed"):
        Spool(tmp_path).write_snapshot(snap)


# --- pending and upload markers ------------------------------------------------------------------


def test_pending_lists_unuploaded_files_oldest_first(tmp_path: Path) -> None:
    spool = Spool(tmp_path)
    later = spool.write_snapshot(make_snapshot({"a": 2}, cut_at=CUT_AT + 30)).path
    earlier = spool.write_snapshot(make_snapshot({"a": 1})).path
    trips = spool.write_snapshot(make_snapshot({"t": 1}, feed="trip_updates")).path
    assert later is not None
    assert earlier is not None
    assert trips is not None

    assert spool.pending() == sorted([earlier, later, trips], key=lambda p: (p.name, p.parent.name))

    spool.mark_uploaded(earlier)
    spool.mark_uploaded(earlier)  # idempotent

    assert earlier not in spool.pending()
    assert spool.is_uploaded(earlier)


# --- fetch log -----------------------------------------------------------------------------------


def read_lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_written_snapshot_is_logged_with_every_field(tmp_path: Path) -> None:
    spool, log = Spool(tmp_path), FetchLog(tmp_path, ingest_version="0.1.0")
    snap = make_snapshot({"a": 1, "b": 2})
    result = spool.write_snapshot(snap)

    log.record_fetch(snap, result)

    [line] = read_lines(tmp_path / "_fetch_log" / "dt=2026-11-13" / "hour=02.jsonl")
    assert line == {
        "event": "fetch",
        "fetched_at": "2026-11-13T02:14:30Z",
        "feed": "vehicle_positions",
        "url_key": "metro_ws",
        "http_status": None,
        "latency_ms": None,
        "bytes": len(snap.data),
        "bytes_gz": len(snap.gz),
        "content_hash": snap.sha256,
        "object_key": object_key(snap),
        "spool_file": spool_name(snap),
        "outcome": "written",
        "feed_header_ts": "2026-11-13T02:14:11Z",
        "n_entities": 2,
        "n_messages": 2,
        "n_unkeyed": 0,
        "n_unframed": 0,
        "partial": False,
        "connected_s": 30.0,
        "interval_s": 30,
        "error": None,
        "ingest_version": "0.1.0",
    }


def test_duplicate_is_logged_without_a_spool_file(tmp_path: Path) -> None:
    spool, log = Spool(tmp_path), FetchLog(tmp_path, ingest_version="0.1.0")
    snap = make_snapshot({"a": 1})
    spool.write_snapshot(snap)
    later = make_snapshot({"a": 1}, cut_at=CUT_AT + 30)

    log.record_fetch(later, spool.write_snapshot(later))

    [line] = read_lines(tmp_path / "_fetch_log" / "dt=2026-11-13" / "hour=02.jsonl")
    assert line["outcome"] == "duplicate"
    assert line["spool_file"] is None
    assert line["content_hash"] == later.sha256


def test_empty_cut_is_logged_as_network_error(tmp_path: Path) -> None:
    log = FetchLog(tmp_path, ingest_version="0.1.0")
    cut = EmptyCut("trip_updates", CUT_AT, 60, connected_s=0.0, reason="disconnected")

    log.record_fetch(cut, None)

    [line] = read_lines(tmp_path / "_fetch_log" / "dt=2026-11-13" / "hour=02.jsonl")
    assert line["outcome"] == "network_error"
    assert line["error"] == "disconnected"
    assert line["object_key"] is None
    assert line["bytes"] is None
    assert line["connected_s"] == 0.0


def test_connection_events_are_logged(tmp_path: Path) -> None:
    log = FetchLog(tmp_path, ingest_version="0.1.0")

    log.record_connection("trip_updates", "disconnect", CUT_AT, close_code=1006, reason="abnormal")
    log.record_connection("trip_updates", "connect", CUT_AT + 2.5)

    lines = read_lines(tmp_path / "_fetch_log" / "dt=2026-11-13" / "hour=02.jsonl")
    assert [(entry["event"], entry["at"], entry["close_code"]) for entry in lines] == [
        ("disconnect", "2026-11-13T02:14:30Z", 1006),
        ("connect", "2026-11-13T02:14:32.500Z", None),
    ]


def test_lines_go_to_the_file_for_their_utc_hour(tmp_path: Path) -> None:
    log = FetchLog(tmp_path, ingest_version="0.1.0")
    log.record_fetch(EmptyCut("trip_updates", CUT_AT, 60, 0.0, "disconnected"), None)
    log.record_fetch(EmptyCut("trip_updates", CUT_AT + 3600, 60, 0.0, "disconnected"), None)

    assert (tmp_path / "_fetch_log" / "dt=2026-11-13" / "hour=02.jsonl").exists()
    assert (tmp_path / "_fetch_log" / "dt=2026-11-13" / "hour=03.jsonl").exists()
