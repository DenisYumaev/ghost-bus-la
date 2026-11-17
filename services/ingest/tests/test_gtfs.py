"""Tests for the GTFS schedule download (pipeline spec, sections 2.2, 2.3, and 4).

The ZIP is fetched over HTTPS on start and daily at 03:00 Los Angeles time, stored in the
spool only when its hash changes, and uploaded by the same uploader as the snapshots. HTTP is
faked with httpx.MockTransport, so nothing touches the network (hard rule 10).
"""

import asyncio
import hashlib
import io
import zipfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from ghostbus_ingest.fetch_log import FetchLog
from ghostbus_ingest.gtfs import GtfsConfig, GtfsDownloader, load_gtfs, next_daily_run
from ghostbus_ingest.spool import Spool, spool_object_key
from ghostbus_ingest.uploader import Uploader
from ingest_fakes import FakeS3, async_test, read_log

LA = ZoneInfo("America/Los_Angeles")
URL = "https://example.test/gtfs_bus.zip"
T0 = datetime(2026, 11, 15, 14, 0, 0, tzinfo=UTC).timestamp()


def make_zip(routes: str = "route_id\n2\n") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("routes.txt", routes)
    return buf.getvalue()


def downloader(tmp_path: Path, handler: httpx.MockTransport) -> tuple[GtfsDownloader, Spool]:
    spool = Spool(tmp_path)
    log = FetchLog(tmp_path, ingest_version="0.1.0")
    client = httpx.AsyncClient(transport=handler)
    return GtfsDownloader(GtfsConfig(URL, "03:00"), spool, log, client), spool


def serving(*responses: httpx.Response | Exception) -> httpx.MockTransport:
    queue = list(responses)

    def handle(request: httpx.Request) -> httpx.Response:
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    return httpx.MockTransport(handle)


# --- schedule -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("now_local", "expected_local"),
    [
        # Later today; then exactly 03:00, which means tomorrow.
        (datetime(2026, 11, 15, 2, 59, tzinfo=LA), datetime(2026, 11, 15, 3, 0, tzinfo=LA)),
        (datetime(2026, 11, 15, 3, 0, tzinfo=LA), datetime(2026, 11, 16, 3, 0, tzinfo=LA)),
        (datetime(2026, 11, 15, 22, 0, tzinfo=LA), datetime(2026, 11, 16, 3, 0, tzinfo=LA)),
        # Spring forward (2027-03-14 02:00 -> 03:00) and fall back (2026-11-01): still 03:00 local.
        (datetime(2027, 3, 13, 12, 0, tzinfo=LA), datetime(2027, 3, 14, 3, 0, tzinfo=LA)),
        (datetime(2026, 10, 31, 12, 0, tzinfo=LA), datetime(2026, 11, 1, 3, 0, tzinfo=LA)),
    ],
)
def test_next_run_is_the_next_0300_los_angeles_across_dst(
    now_local: datetime, expected_local: datetime
) -> None:
    assert next_daily_run(now_local.timestamp(), "03:00") == expected_local.timestamp()


def test_config_is_read_from_feeds_toml(tmp_path: Path) -> None:
    path = tmp_path / "feeds.toml"
    path.write_text(f'[gtfs_static]\nurl = "{URL}"\ndaily_at = "03:00"\n')
    assert load_gtfs(path) == GtfsConfig(URL, "03:00")


@pytest.mark.parametrize(
    "body",
    [
        '[gtfs_static]\nurl = "http://insecure.test/x.zip"\ndaily_at = "03:00"\n',
        '[gtfs_static]\nurl = "https://x.test/x.zip"\ndaily_at = "3am"\n',
        '[gtfs_static]\nurl = "https://x.test/x.zip"\ndaily_at = "25:00"\n',
    ],
)
def test_bad_config_is_rejected(tmp_path: Path, body: str) -> None:
    path = tmp_path / "feeds.toml"
    path.write_text(body)
    with pytest.raises(ValueError, match="gtfs_static"):
        load_gtfs(path)


def test_missing_section_means_no_download(tmp_path: Path) -> None:
    path = tmp_path / "feeds.toml"
    path.write_text("[feeds]\n")
    assert load_gtfs(path) is None


# --- one download ---------------------------------------------------------------------------


@async_test
async def test_a_zips_key_and_its_written_line_share_one_utc_day(tmp_path: Path) -> None:
    # Contract with pipeline/decode (gtfs_sightings): the loader reads only the fetch log of
    # the ZIP key's dt= day, so both must come from the same timestamp, even at 23:59:59.9.
    late = datetime(2026, 11, 15, 23, 59, 59, 900000, tzinfo=UTC).timestamp()
    dl, spool = downloader(tmp_path, serving(httpx.Response(200, content=make_zip())))
    assert await dl.download_once(late) == "written"
    [path] = spool.pending()
    [line] = read_log(tmp_path)
    assert spool_object_key(path).split("/")[2] == "dt=2026-11-15"
    assert line["object_key"] == spool_object_key(path)
    assert line["fetched_at"].startswith("2026-11-15T23:59:59")
    assert (tmp_path / "_fetch_log" / "dt=2026-11-15").is_dir()
    assert not (tmp_path / "_fetch_log" / "dt=2026-11-16").exists()


@async_test
async def test_new_zip_is_spooled_byte_for_byte_and_logged(tmp_path: Path) -> None:
    body = make_zip()
    dl, spool = downloader(tmp_path, serving(httpx.Response(200, content=body)))

    outcome = await dl.download_once(T0)

    assert outcome == "written"
    [path] = spool.pending()
    assert path.read_bytes() == body  # raw bytes, never re-zipped (ADR-001 decision 2)
    sha = hashlib.sha256(body).hexdigest()
    assert path.name == f"20261115T140000Z_{sha[:16]}.zip"
    assert spool_object_key(path) == f"bronze/gtfs_static/dt=2026-11-15/{sha[:16]}.zip"
    [line] = read_log(tmp_path)
    assert line["event"] == "fetch"
    assert line["feed"] == "gtfs_static"
    assert line["outcome"] == "written"
    assert line["http_status"] == 200
    assert line["content_hash"] == sha
    assert line["bytes"] == len(body)
    assert isinstance(line["latency_ms"], int)


@async_test
async def test_unchanged_zip_is_a_duplicate_and_stores_nothing(tmp_path: Path) -> None:
    body = make_zip()
    dl, spool = downloader(tmp_path, serving(httpx.Response(200, content=body)))
    await dl.download_once(T0)
    outcome = await dl.download_once(T0 + 86400)
    assert outcome == "duplicate"
    assert len(spool.pending()) == 1
    assert [x["outcome"] for x in read_log(tmp_path)] == ["written", "duplicate"]


@async_test
async def test_a_changed_zip_is_a_new_version(tmp_path: Path) -> None:
    dl, spool = downloader(
        tmp_path,
        serving(
            httpx.Response(200, content=make_zip("route_id\n2\n")),
            httpx.Response(200, content=make_zip("route_id\n2\n4\n")),
        ),
    )
    await dl.download_once(T0)
    assert await dl.download_once(T0 + 86400) == "written"
    assert len(spool.pending()) == 2


@pytest.mark.parametrize(
    ("response", "outcome", "retry"),
    [
        (httpx.Response(503), "http_error", True),
        (httpx.Response(429), "http_error", True),
        (httpx.Response(404), "http_error", False),  # retrying won't fix a moved file
        (httpx.Response(200, content=b"<html>maintenance</html>"), "http_error", True),
        (httpx.ConnectError("refused"), "network_error", True),
        (httpx.ReadTimeout("slow"), "network_error", True),
    ],
)
@async_test
async def test_failures_store_nothing_and_say_whether_to_retry(
    tmp_path: Path, response: httpx.Response | Exception, outcome: str, retry: bool
) -> None:
    dl, spool = downloader(tmp_path, serving(response))
    assert await dl.download_once(T0) == outcome
    assert spool.pending() == []
    [line] = read_log(tmp_path)
    assert line["outcome"] == outcome
    assert line["error"]
    assert dl.should_retry(outcome, line["http_status"]) is retry


@async_test
async def test_an_oversized_response_is_refused(tmp_path: Path) -> None:
    dl, spool = downloader(tmp_path, serving(httpx.Response(200, content=make_zip())))
    dl.max_bytes = 10
    assert await dl.download_once(T0) == "http_error"
    assert spool.pending() == []


# --- upload and the run loop ----------------------------------------------------------------


@async_test
async def test_the_uploader_stores_the_zip_with_a_conditional_write(tmp_path: Path) -> None:
    body = make_zip()
    dl, spool = downloader(tmp_path, serving(httpx.Response(200, content=body)))
    await dl.download_once(T0)
    s3 = FakeS3()
    report = Uploader(spool, FetchLog(tmp_path, "0.1.0"), s3, "b").upload_once(T0 + 1)
    assert report.written == 1
    [(stored, content_type)] = [
        v for k, v in s3.objects.items() if k.startswith("bronze/gtfs_static/")
    ]
    assert stored == body
    assert content_type == "application/zip"


@async_test
async def test_run_downloads_on_start_retries_then_waits_for_the_daily_slot(
    tmp_path: Path,
) -> None:
    dl, spool = downloader(
        tmp_path,
        serving(httpx.ConnectError("down"), httpx.Response(200, content=make_zip())),
    )
    waits: list[float] = []
    stop = asyncio.Event()
    clock = iter([T0, T0 + 1, T0 + 2, T0 + 3])

    async def fake_wait(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) == 2:
            stop.set()

    await dl.run(stop, clock=lambda: next(clock), wait=fake_wait, rand=lambda: 1.0)

    assert [x["outcome"] for x in read_log(tmp_path)] == ["network_error", "written"]
    assert waits[0] == 1.0  # first retry: backoff, 1 s at full jitter
    assert waits[1] == next_daily_run(T0 + 2, "03:00") - (T0 + 2)  # then the next 03:00 LA
    assert len(spool.pending()) == 1


@async_test
async def test_run_stops_promptly_even_while_waiting(tmp_path: Path) -> None:
    dl, _ = downloader(tmp_path, serving(httpx.Response(200, content=make_zip())))
    stop = asyncio.Event()
    task = asyncio.create_task(dl.run(stop))
    await asyncio.sleep(0.2)  # first download done; now waiting hours for 03:00
    stop.set()
    await asyncio.wait_for(task, timeout=2)


# --- review fixes: memory, shutdown, failures, restarts --------------------------------------


@async_test
async def test_an_endless_body_stops_being_read_just_past_the_cap(tmp_path: Path) -> None:
    sent = 0

    async def endless() -> AsyncIterator[bytes]:
        nonlocal sent
        while True:
            sent += 1024
            yield b"x" * 1024

    dl, spool = downloader(tmp_path, serving(httpx.Response(200, content=endless())))
    dl.max_bytes = 10 * 1024
    assert await dl.download_once(T0) == "http_error"
    assert sent <= 12 * 1024  # stopped within a chunk of the cap, never buffered the rest
    assert spool.pending() == []


@async_test
async def test_a_declared_length_over_the_cap_is_refused_before_reading(tmp_path: Path) -> None:
    response = httpx.Response(200, headers={"Content-Length": "999999999"}, content=b"")
    dl, _ = downloader(tmp_path, serving(response))
    assert await dl.download_once(T0) == "http_error"
    [line] = read_log(tmp_path)
    assert "Content-Length" in line["error"]


@async_test
async def test_an_unexpected_error_is_logged_and_retried_never_raised(tmp_path: Path) -> None:
    dl, spool = downloader(tmp_path, serving(httpx.Response(200, content=make_zip())))
    calls = 0
    real = dl.download_once

    async def flaky(now: float) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("bug")
        return await real(now)

    dl.download_once = flaky  # type: ignore[method-assign]
    stop = asyncio.Event()
    waits: list[float] = []

    async def fake_wait(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) == 2:
            stop.set()

    await dl.run(stop, wait=fake_wait, rand=lambda: 1.0)
    assert waits[0] == 1.0  # the bug was treated like a failure: backoff, not a crash
    assert len(spool.pending()) == 1


@async_test
async def test_stop_cancels_a_download_in_flight(tmp_path: Path) -> None:
    async def trickle() -> AsyncIterator[bytes]:
        while True:
            await asyncio.sleep(0.05)
            yield b"x"

    dl, spool = downloader(tmp_path, serving(httpx.Response(200, content=trickle())))
    stop = asyncio.Event()
    task = asyncio.create_task(dl.run(stop))
    await asyncio.sleep(0.2)
    stop.set()
    await asyncio.wait_for(task, timeout=2)
    assert spool.pending() == []


@async_test
async def test_the_whole_download_has_a_total_time_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def trickle() -> AsyncIterator[bytes]:
        while True:
            await asyncio.sleep(0.05)
            yield b"x"

    monkeypatch.setattr("ghostbus_ingest.gtfs.TIMEOUT_S", 0.3)
    dl, _ = downloader(tmp_path, serving(httpx.Response(200, content=trickle())))
    assert await asyncio.wait_for(dl.download_once(T0), timeout=2) == "network_error"


@pytest.mark.parametrize("n_failures", [10])
@async_test
async def test_after_repeated_failures_it_waits_for_the_daily_slot(
    tmp_path: Path, n_failures: int
) -> None:
    dl, _ = downloader(tmp_path, serving(httpx.Response(503)))
    stop = asyncio.Event()
    waits: list[float] = []

    async def fake_wait(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) == n_failures:
            stop.set()

    await dl.run(stop, clock=lambda: T0, wait=fake_wait, rand=lambda: 1.0)
    assert max(waits[: n_failures - 1]) <= 60.0
    assert waits[n_failures - 1] == next_daily_run(T0, "03:00") - T0


@async_test
async def test_the_same_zip_after_a_restart_is_a_duplicate(tmp_path: Path) -> None:
    body = make_zip()
    dl, _ = downloader(tmp_path, serving(httpx.Response(200, content=body)))
    await dl.download_once(T0)
    restarted, spool = downloader(tmp_path, serving(httpx.Response(200, content=body)))
    assert await restarted.download_once(T0 + 2 * 86400) == "duplicate"  # another UTC day
    assert len(spool.pending()) == 1


@async_test
async def test_a_spool_failure_is_logged_and_leaves_no_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dl, _ = downloader(tmp_path, serving(httpx.Response(200, content=make_zip())))

    def disk_full(src: object, dst: object) -> None:
        raise OSError(28, "No space left on device")

    # os.replace is used only by the spool, so the fetch log can still record the failure.
    monkeypatch.setattr("ghostbus_ingest.spool.os.replace", disk_full)
    assert await dl.download_once(T0) == "spool_error"
    assert list((tmp_path / "gtfs_static").glob("*.tmp")) == []


@async_test
async def test_a_corrupt_zip_in_the_spool_is_set_aside(tmp_path: Path) -> None:
    dl, spool = downloader(tmp_path, serving(httpx.Response(200, content=make_zip())))
    await dl.download_once(T0)
    [path] = spool.pending()
    path.write_bytes(b"damaged")
    s3 = FakeS3()
    report = Uploader(spool, FetchLog(tmp_path, "0.1.0"), s3, "b").upload_once(T0 + 1)
    assert report.corrupt == 1
    assert not any(k.startswith("bronze/gtfs_static/") for k in s3.objects)


@pytest.mark.parametrize(
    ("now_local", "expected_local"),
    [
        # On the change days themselves: inside the repeated hour, and just before the skip.
        (datetime(2026, 11, 1, 1, 30, fold=1, tzinfo=LA), datetime(2026, 11, 1, 3, 0, tzinfo=LA)),
        (datetime(2027, 3, 14, 1, 30, tzinfo=LA), datetime(2027, 3, 14, 3, 0, tzinfo=LA)),
    ],
)
def test_next_run_on_the_dst_change_days(now_local: datetime, expected_local: datetime) -> None:
    assert next_daily_run(now_local.timestamp(), "03:00") == expected_local.timestamp()


def test_gtfs_fetch_lines_leave_stream_only_fields_null(tmp_path: Path) -> None:
    FetchLog(tmp_path, "0.1.0").record_download(T0, "gtfs_static", "k", "network_error")
    [line] = read_log(tmp_path)
    assert line["partial"] is None
    assert line["connected_s"] is None
