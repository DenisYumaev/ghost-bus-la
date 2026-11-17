"""Tests for decoding a compacted day into typed tables (pipeline spec, section 3)."""

import base64
import gzip
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pytest
from ghostbus_decode.compact import compact_day
from ghostbus_decode.decode import NotCompacted, decode_day, decoded_parts

DAY = date(2026, 11, 14)
VP, TU = "vehicle_positions", "trip_updates"


def vehicle(vid: str, epoch: int, lat: float = 34.0) -> str:
    return json.dumps({"id": vid, "vehicle": {
        "position": {"latitude": lat, "longitude": -118.2, "speed": 1.0},
        "timestamp": str(epoch), "vehicle": {"id": vid}}})  # fmt: skip


def trip(tid: str, rel: str, stops: int = 0) -> str:
    stus = [{"stopSequence": i + 1, "stopId": f"S{i}", "arrival": {"time": "1794539700"}}
            for i in range(stops)]  # fmt: skip
    body: dict[str, Any] = {"trip": {"tripId": tid, "startDate": "20261114",
                                     "startTime": "25:10:00", "scheduleRelationship": rel},
                            "timestamp": "1794539600"}  # fmt: skip
    if stus:
        body["stopTimeUpdate"] = stus
    return json.dumps({"id": tid, "tripUpdate": body})


class FakeBucket:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(k for k in self.objects if k.startswith(prefix))

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def put(self, key: str, body: bytes) -> None:
        self.objects[key] = body

    def delete(self, key: str) -> None:
        self.deleted.append(key)
        del self.objects[key]


def store(bucket: FakeBucket, feed: str, cuts: list[tuple[str, list[str]]]) -> None:
    """Put snapshots in bronze and their fetch-log lines, then compact the day."""
    lines = []
    for at, frames in cuts:
        data = ("\n".join(frames) + "\n").encode()
        sha = hashlib.sha256(data).hexdigest()
        bucket.objects[f"bronze/{feed}/dt=2026-11-14/{sha[:16]}.ndjson.gz"] = gzip.compress(
            data, mtime=0
        )
        rec = {"event": "fetch", "feed": feed, "fetched_at": at, "outcome": "written",
               "content_hash": sha, "partial": False}  # fmt: skip
        lines.append(json.dumps(rec))
    log = f"bronze/_fetch_log/dt=2026-11-14/hour=05/{feed}.jsonl"
    bucket.objects[log] = bucket.objects.get(log, b"") + ("\n".join(lines) + "\n").encode()
    compact_day(bucket, feed, DAY)


def query(bucket: FakeBucket, feed: str, table: str, sql: str, tmp_path: Path) -> list[Any]:
    d = tmp_path / table
    d.mkdir(exist_ok=True)
    for k in decoded_parts(bucket, feed, DAY)[table]:
        (d / k.rsplit("/", 1)[-1]).write_bytes(bucket.objects[k])
    with duckdb.connect() as con:
        con.execute("SET TimeZone = 'UTC'")
        con.execute(f"CREATE VIEW t AS SELECT * FROM read_parquet('{d}/*.parquet')")  # noqa: S608
        return con.execute(sql).fetchall()


def test_vehicles_decode_with_snapshot_context(tmp_path: Path) -> None:
    bucket = FakeBucket()
    store(
        bucket, VP, [("2026-11-14T05:00:00Z", [vehicle("1", 1794539500), vehicle("2", 1794539520)])]
    )
    marker = decode_day(bucket, VP, DAY, workdir=tmp_path)
    assert (marker["snapshots"], marker["frames"], marker["rows"], marker["quarantined"]) == (
        1,
        2,
        2,
        0,
    )
    rows = query(bucket, VP, "vehicle_position",
                 "SELECT vehicle_id, lat, CAST(vehicle_ts AS VARCHAR), CAST(feed_ts AS VARCHAR), "
                 "CAST(fetched_at AS VARCHAR) FROM t ORDER BY vehicle_id", tmp_path)  # fmt: skip
    assert rows == [
        # epoch 1794539500 is 2026-11-13 03:11:40 UTC (checked with `date -u -r`)
        ("1", 34.0, "2026-11-13 03:11:40+00", "2026-11-13 03:12:00+00", "2026-11-14 05:00:00+00"),
        ("2", 34.0, "2026-11-13 03:12:00+00", "2026-11-13 03:12:00+00", "2026-11-14 05:00:00+00"),
    ]


def test_trip_updates_one_row_per_stop_and_one_per_cancellation(tmp_path: Path) -> None:
    bucket = FakeBucket()
    store(
        bucket, TU, [("2026-11-14T05:00:00Z", [trip("A", "CANCELED"), trip("B", "SCHEDULED", 2)])]
    )
    marker = decode_day(bucket, TU, DAY, workdir=tmp_path)
    assert marker["rows"] == 3
    rows = query(bucket, TU, "trip_update",
                 "SELECT trip_id, trip_schedule_relationship, stop_sequence, start_date, "
                 "start_time FROM t ORDER BY trip_id, stop_sequence", tmp_path)  # fmt: skip
    assert rows == [
        ("A", "CANCELED", None, date(2026, 11, 14), "25:10:00"),
        ("B", "SCHEDULED", 1, date(2026, 11, 14), "25:10:00"),
        ("B", "SCHEDULED", 2, date(2026, 11, 14), "25:10:00"),
    ]


def test_bad_frames_are_quarantined_with_their_exact_bytes(tmp_path: Path) -> None:
    bucket = FakeBucket()
    bad = vehicle("3", 1794539500, lat=95.0)
    store(bucket, VP, [("2026-11-14T05:00:00Z", [vehicle("1", 1794539500), bad, "{torn"])])
    marker = decode_day(bucket, VP, DAY, workdir=tmp_path)
    assert (marker["rows"], marker["quarantined"]) == (1, 2)
    assert marker["reasons"] == {"bad:vehicle.position.latitude": 1, "not_json": 1}
    q = query(bucket, VP, "quarantine", "SELECT reason, raw_b64 FROM t ORDER BY reason", tmp_path)
    assert [(r, base64.b64decode(b)) for r, b in q] == [
        ("bad:vehicle.position.latitude", bad.encode()), ("not_json", b"{torn"),
    ]  # fmt: skip


def test_one_fingerprint_row_per_snapshot(tmp_path: Path) -> None:
    bucket = FakeBucket()
    extra = json.dumps({**json.loads(vehicle("9", 1794539500)), "occupancyStatus": "FULL"})
    store(bucket, VP, [("2026-11-14T05:00:00Z", [vehicle("1", 1794539500)]),
                       ("2026-11-14T05:00:30Z", [vehicle("1", 1794539510)]),
                       ("2026-11-14T05:01:00Z", [extra])])  # fmt: skip
    decode_day(bucket, VP, DAY, workdir=tmp_path)
    rows = query(
        bucket,
        VP,
        "schema_fingerprint",
        "SELECT fingerprint, n_frames FROM t ORDER BY fetched_at",
        tmp_path,
    )
    assert len(rows) == 3
    assert rows[0][0] == rows[1][0] != rows[2][0]  # a new field changes the fingerprint


def test_rerunning_gives_the_same_rows_and_removes_the_old_run(tmp_path: Path) -> None:
    bucket = FakeBucket()
    store(bucket, VP, [("2026-11-14T05:00:00Z", [vehicle("1", 1794539500)])])
    first = decode_day(bucket, VP, DAY, workdir=tmp_path, run_id="r1")
    sql = "SELECT vehicle_id, lat, CAST(vehicle_ts AS VARCHAR), CAST(fetched_at AS VARCHAR) FROM t"
    before = query(bucket, VP, "vehicle_position", sql, tmp_path)
    decode_day(bucket, VP, DAY, workdir=tmp_path, run_id="r2")
    assert query(bucket, VP, "vehicle_position", sql, tmp_path) == before
    old_parts = {k for keys in first["part_keys"].values() for k in keys}
    assert old_parts <= set(bucket.deleted)


def test_a_day_that_isnt_compacted_is_refused(tmp_path: Path) -> None:
    with pytest.raises(NotCompacted):
        decode_day(FakeBucket(), VP, DAY, workdir=tmp_path)


def test_rejects_an_unknown_feed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="feed"):
        decode_day(FakeBucket(), "gtfs_static", DAY, workdir=tmp_path)


def test_no_marker_means_no_decoded_parts() -> None:
    assert decoded_parts(FakeBucket(), VP, DAY) == {}


def test_a_frame_ingest_had_to_wrap_is_unwrapped_and_decoded(tmp_path: Path) -> None:
    # Ingest stores a frame containing a newline as {"_unframed_b64": ...} (snapshot.py).
    pretty = json.dumps(json.loads(vehicle("7", 1794539500)), indent=2).encode()
    wrapped = json.dumps({"_unframed_b64": base64.b64encode(pretty).decode()})
    bucket = FakeBucket()
    store(bucket, VP, [("2026-11-14T05:00:00Z", [wrapped, '{"_unframed_b64": "!!"}'])])
    m = decode_day(bucket, VP, DAY, workdir=tmp_path)
    assert (m["rows"], m["reasons"]) == (1, {"bad:_unframed_b64": 1})
    assert query(bucket, VP, "vehicle_position", "SELECT vehicle_id FROM t", tmp_path) == [("7",)]


def test_extreme_but_valid_numbers_reach_parquet_or_quarantine_never_crash(tmp_path: Path) -> None:
    big_seq = json.loads(trip("B", "SCHEDULED", 1))
    big_seq["tripUpdate"]["stopTimeUpdate"][0]["stopSequence"] = 2**31 - 1
    too_big = json.loads(trip("C", "SCHEDULED", 1))
    too_big["tripUpdate"]["stopTimeUpdate"][0]["stopSequence"] = 3_000_000_000  # legal uint32
    long_ts = json.loads(trip("D", "CANCELED"))
    long_ts["tripUpdate"]["timestamp"] = "9" * 5000
    bucket = FakeBucket()
    frames = [json.dumps(big_seq), json.dumps(too_big), json.dumps(long_ts)]
    store(bucket, TU, [("2026-11-14T05:00:00Z", frames)])
    m = decode_day(bucket, TU, DAY, workdir=tmp_path)
    assert m["rows"] == 1
    assert m["reasons"] == {"bad:tripUpdate.stopTimeUpdate[].stopSequence": 1,
                            "bad:tripUpdate.timestamp": 1}  # fmt: skip
    seqs = query(bucket, TU, "trip_update", "SELECT stop_sequence FROM t", tmp_path)
    assert seqs == [(2**31 - 1,)]


def test_a_blank_frame_is_quarantined_not_dropped(tmp_path: Path) -> None:
    bucket = FakeBucket()
    store(bucket, VP, [("2026-11-14T05:00:00Z", [vehicle("1", 1794539500), "   "])])
    m = decode_day(bucket, VP, DAY, workdir=tmp_path)
    assert (m["frames"], m["rows"], m["reasons"]) == (2, 1, {"empty": 1})


def test_trip_update_feed_ts_is_the_newest_entity_timestamp(tmp_path: Path) -> None:
    older = json.loads(trip("A", "CANCELED"))
    older["tripUpdate"]["timestamp"] = "1794539000"
    bucket = FakeBucket()
    store(bucket, TU, [("2026-11-14T05:00:00Z", [json.dumps(older), trip("B", "CANCELED")])])
    decode_day(bucket, TU, DAY, workdir=tmp_path)
    assert query(
        bucket, TU, "trip_update", "SELECT DISTINCT CAST(feed_ts AS VARCHAR) FROM t", tmp_path
    ) == [("2026-11-13 03:13:20+00",)]  # epoch 1794539600 (date -u -r)


def test_the_marker_records_which_compaction_run_it_read(tmp_path: Path) -> None:
    from ghostbus_decode.compact import compaction_marker

    bucket = FakeBucket()
    store(bucket, VP, [("2026-11-14T05:00:00Z", [vehicle("1", 1794539500)])])
    m = decode_day(bucket, VP, DAY, workdir=tmp_path)
    source = compaction_marker(bucket, VP, DAY)
    assert source is not None
    assert m["compaction_run"] == source["run"]


def test_a_crash_mid_run_leaves_the_previous_decode_readable(tmp_path: Path) -> None:
    bucket = FakeBucket()
    store(bucket, VP, [("2026-11-14T05:00:00Z", [vehicle("1", 1794539500)])])
    decode_day(bucket, VP, DAY, workdir=tmp_path, run_id="r1")
    sql = "SELECT vehicle_id FROM t"
    before = query(bucket, VP, "vehicle_position", sql, tmp_path)
    real_put = bucket.put
    calls = {"n": 0}

    def flaky_put(key: str, body: bytes) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise ConnectionError("boom")
        real_put(key, body)

    bucket.put = flaky_put  # type: ignore[method-assign]
    with pytest.raises(ConnectionError):
        decode_day(bucket, VP, DAY, workdir=tmp_path, run_id="r2")
    bucket.put = real_put  # type: ignore[method-assign]
    assert query(bucket, VP, "vehicle_position", sql, tmp_path) == before
