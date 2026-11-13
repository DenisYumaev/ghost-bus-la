"""Tests for the uploader: spool to S3, resume after failure, fetch-log upload, janitor.

Pipeline spec section 2.4, steps 4 and 5; ADR-004. A small in-memory S3 implements the
conditional-write rule itself (412 when the key exists), so outages, crashes, and resumes can
be simulated without AWS.
"""

import gzip
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from ghostbus_ingest.fetch_log import FetchLog
from ghostbus_ingest.snapshot import Snapshot, SnapshotBuffer
from ghostbus_ingest.spool import Spool, object_key, spool_object_key
from ghostbus_ingest.uploader import Uploader

BUCKET = "test-bucket"
T0 = datetime(2026, 11, 13, 2, 14, 30, tzinfo=UTC).timestamp()
HOUR = 3600.0


class FakeS3:
    """Just enough S3: PutObject with If-None-Match, plus switchable failures."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str | None]] = {}
        self.fail_with: Exception | None = None
        self.puts = 0

    def put_object(self, **kw: Any) -> dict[str, Any]:
        self.puts += 1
        if self.fail_with is not None:
            raise self.fail_with
        if kw.get("IfNoneMatch") == "*" and kw["Key"] in self.objects:
            raise client_error("PreconditionFailed", 412)
        self.objects[kw["Key"]] = (kw["Body"], kw.get("ContentType"))
        return {"ETag": '"e"'}

    def get_object(self, **kw: Any) -> dict[str, Any]:
        raise NotImplementedError

    def list_object_versions(self, **kw: Any) -> dict[str, Any]:
        raise NotImplementedError

    def delete_object(self, **kw: Any) -> dict[str, Any]:
        raise AssertionError("ingest must never delete anything in S3")


def client_error(code: str, status: int) -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": code}, "ResponseMetadata": {"HTTPStatusCode": status}},
        "PutObject",
    )


def snapshot(value: int, cut_at: float = T0, feed: str = "vehicle_positions") -> Snapshot:
    buf = SnapshotBuffer(feed, 30, interval_start=cut_at - 30)
    buf.on_connect(cut_at - 30)
    buf.on_message(json.dumps({"id": "a", "vehicle": {"v": value}}).encode(), cut_at - 1)
    snap = buf.cut(cut_at)
    assert isinstance(snap, Snapshot)
    return snap


@pytest.fixture
def parts(tmp_path: Path) -> tuple[Spool, FetchLog, FakeS3, Uploader]:
    spool, log, s3 = Spool(tmp_path), FetchLog(tmp_path, ingest_version="0.1.0"), FakeS3()
    return spool, log, s3, Uploader(spool, log, s3, BUCKET)


def upload_lines(tmp_path: Path) -> list[dict[str, Any]]:
    lines = []
    for path in sorted((tmp_path / "_fetch_log").rglob("*.jsonl")):
        lines += [json.loads(line) for line in path.read_text().splitlines()]
    return [line for line in lines if line["event"] == "upload"]


# --- keys ----------------------------------------------------------------------------------------


def test_spool_file_name_maps_back_to_its_object_key(tmp_path: Path) -> None:
    snap = snapshot(1)
    path = Spool(tmp_path).write_snapshot(snap).path
    assert path is not None
    assert spool_object_key(path) == object_key(snap)


@pytest.mark.parametrize("name", ["junk.ndjson.gz", "20261113T021430Z_short.ndjson.gz"])
def test_malformed_spool_names_are_rejected(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError, match="spool file name"):
        spool_object_key(tmp_path / "vehicle_positions" / name)


# --- uploading snapshots -------------------------------------------------------------------------


def test_pending_snapshot_is_uploaded_marked_and_logged(
    tmp_path: Path, parts: tuple[Spool, FetchLog, FakeS3, Uploader]
) -> None:
    spool, _log, s3, uploader = parts
    snap = snapshot(1)
    path = spool.write_snapshot(snap).path
    assert path is not None

    report = uploader.upload_once(now=T0 + 5)

    assert (report.written, report.duplicate, report.failed) == (1, 0, 0)
    assert s3.objects[object_key(snap)] == (snap.gz, "application/gzip")
    assert spool.is_uploaded(path)
    [line] = upload_lines(tmp_path)
    assert line["object_key"] == object_key(snap)
    assert line["outcome"] == "written"
    assert line["spool_file"] == path.name


def test_bytes_already_in_s3_count_as_a_successful_duplicate(
    parts: tuple[Spool, FetchLog, FakeS3, Uploader],
) -> None:
    spool, _log, s3, uploader = parts
    snap = snapshot(1)
    path = spool.write_snapshot(snap).path
    assert path is not None
    s3.objects[object_key(snap)] = (snap.gz, "application/gzip")

    report = uploader.upload_once(now=T0 + 5)

    assert (report.written, report.duplicate) == (0, 1)
    assert spool.is_uploaded(path)


@pytest.mark.parametrize(
    "failure",
    [
        client_error("SlowDown", 503),
        client_error("AccessDenied", 403),
        EndpointConnectionError(endpoint_url="https://s3"),
    ],
)
def test_an_s3_failure_keeps_the_file_and_stops_the_round(
    parts: tuple[Spool, FetchLog, FakeS3, Uploader], failure: Exception
) -> None:
    spool, _log, s3, uploader = parts
    first = spool.write_snapshot(snapshot(1)).path
    second = spool.write_snapshot(snapshot(2, cut_at=T0 + 30)).path
    s3.fail_with = failure

    report = uploader.upload_once(now=T0 + 35)

    assert report.failed == 1
    assert report.error is not None
    assert s3.puts == 1, "stop after the first failure; S3 is probably down"
    assert spool.pending() == [first, second]


def test_uploads_resume_after_an_outage(parts: tuple[Spool, FetchLog, FakeS3, Uploader]) -> None:
    spool, _log, s3, uploader = parts
    spool.write_snapshot(snapshot(1))
    s3.fail_with = EndpointConnectionError(endpoint_url="https://s3")
    uploader.upload_once(now=T0 + 5)
    spool.write_snapshot(snapshot(2, cut_at=T0 + 30))
    s3.fail_with = None

    report = uploader.upload_once(now=T0 + 35)

    assert report.written == 2
    assert spool.pending() == []


def test_a_crash_after_upload_but_before_the_marker_is_harmless(
    parts: tuple[Spool, FetchLog, FakeS3, Uploader],
) -> None:
    spool, _log, s3, uploader = parts
    path = spool.write_snapshot(snapshot(1)).path
    assert path is not None
    uploader.upload_once(now=T0 + 5)
    path.with_name(path.name + ".uploaded").unlink()  # the crash: S3 has it, the marker doesn't

    report = uploader.upload_once(now=T0 + 10)

    assert report.duplicate == 1  # the 412 proves the bytes are safe
    assert len(s3.objects) == 1
    assert spool.is_uploaded(path)


def test_a_corrupt_spool_file_is_set_aside_and_never_uploaded(
    tmp_path: Path, parts: tuple[Spool, FetchLog, FakeS3, Uploader]
) -> None:
    spool, _log, s3, uploader = parts
    bad = spool.write_snapshot(snapshot(1)).path
    good = spool.write_snapshot(snapshot(2, cut_at=T0 + 30)).path
    assert bad is not None
    assert good is not None
    bad.write_bytes(gzip.compress(b"not what the name's hash says", mtime=0))

    report = uploader.upload_once(now=T0 + 35)

    assert report.corrupt == 1
    assert report.written == 1
    assert not bad.exists()
    assert bad.with_name(bad.name + ".corrupt").exists()
    assert spool_object_key(bad) not in s3.objects
    assert any(line["outcome"] == "corrupt" for line in upload_lines(tmp_path))


# --- uploading the fetch log ---------------------------------------------------------------------


def log_keys(s3: FakeS3) -> list[str]:
    return sorted(k for k in s3.objects if k.startswith("bronze/_fetch_log/"))


def test_a_closed_hour_of_fetch_log_is_uploaded_content_addressed(
    parts: tuple[Spool, FetchLog, FakeS3, Uploader],
) -> None:
    _spool, log, s3, uploader = parts
    log.record_connection("trip_updates", "connect", T0)  # hour 02

    uploader.upload_once(now=T0 + 10)  # still hour 02: not closed
    assert log_keys(s3) == []

    uploader.upload_once(now=T0 + HOUR)  # hour 03: hour 02 is closed
    [key] = log_keys(s3)
    assert key.startswith("bronze/_fetch_log/dt=2026-11-13/hour=02/")
    assert key.endswith(".jsonl")
    assert s3.objects[key][1] == "application/x-ndjson"

    uploader.upload_once(now=T0 + HOUR + 10)  # unchanged: not uploaded again
    assert len(log_keys(s3)) == 1


def test_the_open_hour_is_uploaded_on_the_final_pass_and_again_when_it_grows(
    parts: tuple[Spool, FetchLog, FakeS3, Uploader],
) -> None:
    _spool, log, s3, uploader = parts
    log.record_connection("trip_updates", "connect", T0)

    uploader.upload_once(now=T0 + 10, final=True)  # shutdown mid-hour
    assert len(log_keys(s3)) == 1

    log.record_connection("trip_updates", "disconnect", T0 + 20)  # after the restart
    uploader.upload_once(now=T0 + HOUR)

    # Two objects for hour 02, different content, different keys; readers take the union.
    assert len(log_keys(s3)) == 2


# --- janitor -------------------------------------------------------------------------------------


def test_janitor_deletes_only_uploaded_files_older_than_48_hours(
    parts: tuple[Spool, FetchLog, FakeS3, Uploader],
) -> None:
    spool, _log, s3, uploader = parts
    old_uploaded = spool.write_snapshot(snapshot(1)).path
    old_not_uploaded = spool.write_snapshot(snapshot(2, cut_at=T0 + 30)).path
    recent_uploaded = spool.write_snapshot(snapshot(3, cut_at=T0 + 47 * HOUR)).path
    assert old_uploaded is not None
    assert old_not_uploaded is not None
    assert recent_uploaded is not None
    spool.mark_uploaded(old_uploaded)
    spool.mark_uploaded(recent_uploaded)
    s3.fail_with = EndpointConnectionError(endpoint_url="https://s3")  # keep the middle one pending

    uploader.upload_once(now=T0 + 49 * HOUR)

    assert not old_uploaded.exists()
    assert not old_uploaded.with_name(old_uploaded.name + ".uploaded").exists()
    assert old_not_uploaded.exists(), "never delete a file that isn't in S3"
    assert recent_uploaded.exists()


def test_janitor_deletes_old_fetch_log_files_only_once_uploaded(
    tmp_path: Path, parts: tuple[Spool, FetchLog, FakeS3, Uploader]
) -> None:
    _spool, log, s3, uploader = parts
    log.record_connection("trip_updates", "connect", T0)
    path = log.path_for(T0)

    s3.fail_with = EndpointConnectionError(endpoint_url="https://s3")
    uploader.upload_once(now=T0 + 49 * HOUR)
    assert path.exists(), "not uploaded yet, so kept"

    s3.fail_with = None
    uploader.upload_once(now=T0 + 49 * HOUR)  # uploads it
    uploader.upload_once(now=T0 + 49 * HOUR + 1)  # now it can go
    assert not path.exists()


# --- the loop ------------------------------------------------------------------------------------


def test_run_backs_off_on_failure_and_does_a_final_pass_on_stop(
    parts: tuple[Spool, FetchLog, FakeS3, Uploader],
) -> None:
    spool, log, s3, uploader = parts
    spool.write_snapshot(snapshot(1))
    log.record_connection("trip_updates", "connect", T0)
    s3.fail_with = EndpointConnectionError(endpoint_url="https://s3")
    stop = threading.Event()
    waits: list[float] = []

    def fake_wait(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) == 2:
            s3.fail_with = None  # S3 recovers
        if len(waits) == 3:
            stop.set()

    uploader.run(stop, interval_s=10.0, clock=lambda: T0 + 5, wait=fake_wait, rand=lambda: 1.0)

    assert waits == [1.0, 2.0, 10.0]  # backoff 1 s, 2 s, then the normal interval
    assert spool.pending() == []
    assert len(log_keys(s3)) == 1, "the final pass uploads the still-open hour"
