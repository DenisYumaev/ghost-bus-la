"""Tests for the ingest service entry point: settings, wiring, shutdown, failure handling.

The whole service runs end to end against the fake Metro server and the fake S3: both streams
cut snapshots, and on stop the uploader's final pass stores everything.
"""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from ghostbus_ingest import service
from ghostbus_ingest.heartbeat import Heartbeat
from ghostbus_ingest.service import Settings, run_service
from ghostbus_ingest.stream import FeedConfig, StreamRunner
from ingest_fakes import FakeMetro, FakeS3, async_test, fake_metro, fixture_frames

# --- settings ------------------------------------------------------------------------------------


def test_settings_from_env_with_defaults() -> None:
    settings = Settings.from_env({"GHOSTBUS_BUCKET": "my-bucket"})

    assert settings.bucket == "my-bucket"
    assert settings.spool_dir == Path("/var/lib/ghostbus/spool")
    assert settings.feeds_config == Path("config/feeds.toml")
    assert settings.region == "us-west-2"
    assert settings.upload_interval_s == 10.0
    assert settings.health_port == 8081


def test_settings_from_env_overrides() -> None:
    settings = Settings.from_env(
        {
            "GHOSTBUS_BUCKET": "b",
            "GHOSTBUS_SPOOL_DIR": "/tmp/spool",  # noqa: S108 - a path string in a test
            "GHOSTBUS_FEEDS_CONFIG": "/app/config/feeds.toml",
            "AWS_REGION": "us-east-1",
            "GHOSTBUS_UPLOAD_INTERVAL_S": "5",
        }
    )
    assert settings.spool_dir == Path("/tmp/spool")  # noqa: S108
    assert settings.region == "us-east-1"
    assert settings.upload_interval_s == 5.0


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({}, "GHOSTBUS_BUCKET"),
        ({"GHOSTBUS_BUCKET": ""}, "GHOSTBUS_BUCKET"),
        ({"GHOSTBUS_BUCKET": "b", "GHOSTBUS_UPLOAD_INTERVAL_S": "0"}, "GHOSTBUS_UPLOAD_INTERVAL_S"),
        (
            {"GHOSTBUS_BUCKET": "b", "GHOSTBUS_UPLOAD_INTERVAL_S": "soon"},
            "GHOSTBUS_UPLOAD_INTERVAL_S",
        ),
        ({"GHOSTBUS_BUCKET": "b", "GHOSTBUS_HEALTH_PORT": "http"}, "GHOSTBUS_HEALTH_PORT"),
        ({"GHOSTBUS_BUCKET": "b", "GHOSTBUS_HEALTH_PORT": "70000"}, "GHOSTBUS_HEALTH_PORT"),
    ],
)
def test_bad_settings_are_rejected_with_the_variable_named(
    env: dict[str, str], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        Settings.from_env(env)


def test_main_exits_2_with_a_clear_log_line_when_misconfigured(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GHOSTBUS_BUCKET", raising=False)

    assert service.main() == 2

    [line] = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert line["event"] == "config_error"
    assert "GHOSTBUS_BUCKET" in line["error"]


# --- running -------------------------------------------------------------------------------------


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        bucket="test-bucket",
        spool_dir=tmp_path,
        feeds_config=Path("unused.toml"),
        region="us-west-2",
        upload_interval_s=0.2,
        health_port=0,  # any free port; tests must never collide on 8081
    )


async def run_briefly(
    tmp_path: Path, feeds: dict[str, FeedConfig], s3: FakeS3, seconds: float
) -> int:
    stop = asyncio.Event()
    task = asyncio.create_task(run_service(settings_for(tmp_path), feeds, s3, stop))
    await asyncio.sleep(seconds)
    stop.set()
    return await asyncio.wait_for(task, timeout=10)


@async_test
async def test_both_streams_run_and_everything_is_uploaded_by_shutdown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    s3 = FakeS3()
    vp = FakeMetro(fixture_frames("vehicle_positions_45s.jsonl.gz"))
    tu = FakeMetro(fixture_frames("trip_updates_45s.jsonl.gz"))
    async with fake_metro(vp) as vp_url, fake_metro(tu) as tu_url:
        feeds = {
            "vehicle_positions": FeedConfig("vehicle_positions", vp_url, 1),
            "trip_updates": FeedConfig("trip_updates", tu_url, 1),
        }
        code = await run_briefly(tmp_path, feeds, s3, 2.6)

    assert code == 0
    keys = sorted(s3.objects)
    assert any(k.startswith("bronze/vehicle_positions/") for k in keys)
    assert any(k.startswith("bronze/trip_updates/") for k in keys)
    assert any(k.startswith("bronze/_fetch_log/") for k in keys), "final pass uploads the open hour"
    for feed in ("vehicle_positions", "trip_updates"):
        spooled = list((tmp_path / feed).glob("*.ndjson.gz"))
        assert spooled
        assert all((p.parent / (p.name + ".uploaded")).exists() for p in spooled)

    events = [json.loads(x)["event"] for x in capsys.readouterr().out.splitlines()]
    assert events[0] == "service_start"
    assert events[-1] == "service_stop"


@async_test
async def test_a_crashed_stream_stops_the_service_with_exit_code_1_after_a_final_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    real_run = StreamRunner.run

    async def run_or_crash(self: StreamRunner, stop: asyncio.Event) -> None:
        if self.feed.name == "vehicle_positions":
            await asyncio.sleep(1.2)
            raise RuntimeError("a bug in the stream")
        await real_run(self, stop)

    monkeypatch.setattr(StreamRunner, "run", run_or_crash)
    s3 = FakeS3()
    tu = FakeMetro(fixture_frames("trip_updates_45s.jsonl.gz"))
    async with fake_metro(tu) as tu_url:
        feeds = {
            "vehicle_positions": FeedConfig("vehicle_positions", "ws://127.0.0.1:9", 1),
            "trip_updates": FeedConfig("trip_updates", tu_url, 1),
        }
        stop = asyncio.Event()
        code = await asyncio.wait_for(
            run_service(settings_for(tmp_path), feeds, s3, stop), timeout=10
        )

    # Exit non-zero so Docker restarts the container; but save and upload what we have first.
    assert code == 1
    assert any(k.startswith("bronze/trip_updates/") for k in s3.objects)
    logged = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    crash = next(e for e in logged if e["event"] == "stream_crashed")
    assert crash["feed"] == "vehicle_positions"
    assert "a bug in the stream" in crash["error"]


@async_test
async def test_stale_temp_files_are_cleaned_at_startup(tmp_path: Path) -> None:
    feed_dir = tmp_path / "trip_updates"
    feed_dir.mkdir()
    stale = feed_dir / "20200101T000000Z_0000000000000000.ndjson.gz.tmp"
    stale.write_bytes(b"left by a crash")

    tu = FakeMetro(fixture_frames("trip_updates_45s.jsonl.gz"))
    async with fake_metro(tu) as tu_url:
        feeds = {"trip_updates": FeedConfig("trip_updates", tu_url, 1)}
        await run_briefly(tmp_path, feeds, FakeS3(), 0.3)

    assert not stale.exists()


@async_test
async def test_a_crashed_uploader_stops_the_service_with_exit_code_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A dead uploader would let the spool fill silently, so it must take the service down.
    from ghostbus_ingest.uploader import Uploader

    def crash(self: Uploader, stop: object, **kwargs: object) -> None:
        raise RuntimeError("a bug in the uploader")

    monkeypatch.setattr(Uploader, "run", crash)
    tu = FakeMetro(fixture_frames("trip_updates_45s.jsonl.gz"))
    async with fake_metro(tu) as tu_url:
        feeds = {"trip_updates": FeedConfig("trip_updates", tu_url, 1)}
        code = await asyncio.wait_for(
            run_service(settings_for(tmp_path), feeds, FakeS3(), asyncio.Event()), timeout=10
        )

    assert code == 1
    events = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert any(e["event"] == "uploader_crashed" and "uploader" in e["error"] for e in events)
    assert events[-1] == {**events[-1], "event": "service_stop", "exit_code": 1}


@async_test
async def test_healthy_service_pings_the_heartbeat_once_per_fast_cycle(tmp_path: Path) -> None:
    pings: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        pings.append(asyncio.get_running_loop().time())
        return httpx.Response(200)

    vp = FakeMetro(fixture_frames("vehicle_positions_45s.jsonl.gz"))
    tu = FakeMetro(fixture_frames("trip_updates_45s.jsonl.gz"))
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client,
        fake_metro(vp) as vp_url,
        fake_metro(tu) as tu_url,
    ):
        feeds = {
            "vehicle_positions": FeedConfig("vehicle_positions", vp_url, 1),
            "trip_updates": FeedConfig("trip_updates", tu_url, 2),
        }
        stop = asyncio.Event()
        heartbeat = Heartbeat("https://hc-ping.com/test", client)
        task = asyncio.create_task(
            run_service(settings_for(tmp_path), feeds, FakeS3(), stop, heartbeat)
        )
        await asyncio.sleep(3.4)
        stop.set()
        assert await asyncio.wait_for(task, timeout=10) == 0

    # vehicle_positions (1 s) is the fastest feed: about one ping per second, not one per cut
    # of every feed. Allow for the first, partial interval and the final cut on stop.
    assert 2 <= len(pings) <= 5


@async_test
async def test_no_heartbeat_while_a_feed_is_failing(tmp_path: Path) -> None:
    pings: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        pings.append(asyncio.get_running_loop().time())
        return httpx.Response(200)

    vp = FakeMetro(fixture_frames("vehicle_positions_45s.jsonl.gz"))
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client,
        fake_metro(vp) as vp_url,
    ):
        feeds = {
            "vehicle_positions": FeedConfig("vehicle_positions", vp_url, 1),
            "trip_updates": FeedConfig("trip_updates", "ws://127.0.0.1:9", 1),  # never connects
        }
        stop = asyncio.Event()
        start = asyncio.get_running_loop().time()
        task = asyncio.create_task(
            run_service(
                settings_for(tmp_path), feeds, FakeS3(), stop, Heartbeat("https://h/x", client)
            )
        )
        await asyncio.sleep(5.5)
        stop.set()
        await asyncio.wait_for(task, timeout=10)

    # trip_updates never succeeds, so once its 3-interval grace (3 s) is over, pings stop
    # even though vehicle_positions is fine. This is what makes a dead stream page the owner.
    assert pings, "pings during the grace period show the heartbeat was wired up"
    assert all(t - start < 3.6 for t in pings)
