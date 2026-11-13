"""Tests for ghostbus_ingest.stream: the WebSocket client that feeds the snapshot buffer.

A real WebSocket server on localhost replays the recorded fixtures, so the client is exercised
end to end with nothing touching Metro (hard rule 10). Intervals are 1 second to keep this fast.
Spec: docs/spec/01-data-pipeline.md section 2.3.
"""

import asyncio
import gzip
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from ghostbus_ingest.fetch_log import FetchLog
from ghostbus_ingest.spool import Spool
from ghostbus_ingest.stream import USER_AGENT, FeedConfig, StreamRunner, load_feeds
from ingest_fakes import FakeMetro, async_test, fake_metro, fixture_frames, iso, read_log

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[3]


async def run_for(runner: StreamRunner, seconds: float) -> None:
    stop = asyncio.Event()
    task = asyncio.create_task(runner.run(stop))
    await asyncio.sleep(seconds)
    stop.set()
    await asyncio.wait_for(task, timeout=5)


def make_runner(
    tmp_path: Path, url: str, backoff: Callable[[int], float] = lambda attempt: 0.05
) -> StreamRunner:
    feed = FeedConfig("trip_updates", url, interval_s=1)
    return StreamRunner(feed, Spool(tmp_path), FetchLog(tmp_path, "0.1.0"), backoff=backoff)


# --- config --------------------------------------------------------------------------------------


def test_repo_feed_config_loads_both_streams() -> None:
    feeds = load_feeds(REPO_ROOT / "config" / "feeds.toml")
    assert feeds["vehicle_positions"] == FeedConfig(
        "vehicle_positions", "wss://api.metro.net/ws/LACMTA/vehicle_positions", 30
    )
    assert feeds["trip_updates"].interval_s == 60


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('[feeds.weather]\nurl = "wss://x"\ninterval_s = 30\n', "unknown feed"),
        ('[feeds.trip_updates]\nurl = "http://x"\ninterval_s = 60\n', "wss://"),
        ('[feeds.trip_updates]\nurl = "wss://x"\ninterval_s = 0\n', "interval_s"),
        ('[feeds.trip_updates]\nurl = "wss://x"\ninterval_s = 7\n', "interval_s"),
    ],
)
def test_bad_feed_config_is_rejected(tmp_path: Path, body: str, message: str) -> None:
    path = tmp_path / "feeds.toml"
    path.write_text(body)
    with pytest.raises(ValueError, match=message):
        load_feeds(path)


# --- streaming -----------------------------------------------------------------------------------


@async_test
async def test_snapshots_hold_the_exact_frames_received(tmp_path: Path) -> None:
    frames = fixture_frames()
    odd = b'{"id" :  "odd-spacing", "tripUpdate": {"trip": {}} }'  # spacing must survive
    server = FakeMetro([*frames, odd])
    async with fake_metro(server) as url:
        await run_for(make_runner(tmp_path, url), 2.6)

    files = sorted((tmp_path / "trip_updates").glob("*.ndjson.gz"))
    assert len(files) >= 2
    sent = set(frames) | {odd}
    for path in files:
        for line in gzip.decompress(path.read_bytes()).splitlines():
            assert line in sent, "every stored line must be a frame exactly as sent"
    assert any(odd in gzip.decompress(p.read_bytes()).splitlines() for p in files)


@async_test
async def test_one_connection_per_stream_with_the_project_user_agent(tmp_path: Path) -> None:
    server = FakeMetro(fixture_frames())
    async with fake_metro(server) as url:
        await run_for(make_runner(tmp_path, url), 1.5)

    assert server.max_concurrent == 1
    assert server.user_agents == [USER_AGENT]
    assert USER_AGENT.startswith("ghost-bus-la/")
    assert "github.com/DenisYumaev/ghost-bus-la" in USER_AGENT


@async_test
async def test_reconnects_after_a_drop_and_logs_the_close_code(tmp_path: Path) -> None:
    # About 1.5 s in (frames go out about 1 ms apart), so the drop lands in a later interval
    # that would otherwise be complete, not in the first one, which is always partial.
    server = FakeMetro(fixture_frames(), drop_after=1300)
    async with fake_metro(server) as url:
        await run_for(make_runner(tmp_path, url), 3.4)

    assert server.connections >= 2
    events = [
        (e["event"], e.get("close_code")) for e in read_log(tmp_path) if e["event"] != "fetch"
    ]
    assert events[:3] == [("connect", None), ("disconnect", 1011), ("connect", None)]
    # The interval that contains the drop must be partial. (The first interval is always
    # partial because ingest starts mid-interval, so "any partial" would prove nothing.)
    log = read_log(tmp_path)
    drop_at = iso(next(e["at"] for e in log if e["event"] == "disconnect"))
    [interval] = [
        e
        for e in log
        if e["event"] == "fetch" and iso(e["fetched_at"]) - 1 < drop_at <= iso(e["fetched_at"])
    ]
    assert interval["partial"] is True
    assert interval["connected_s"] < 1.0


@async_test
async def test_unreachable_server_logs_network_errors_and_keeps_retrying(tmp_path: Path) -> None:
    attempts: list[int] = []

    def counting_backoff(attempt: int) -> float:
        attempts.append(attempt)
        return 0.05

    # Nothing listens on this port: every connect fails.
    runner = make_runner(tmp_path, "ws://127.0.0.1:9", backoff=counting_backoff)
    await run_for(runner, 2.4)

    assert len(attempts) >= 5
    assert attempts[:3] == [0, 1, 2], "backoff grows while failures continue"
    log = read_log(tmp_path)
    assert any(e["event"] == "connect_failed" for e in log)
    fetches = [e for e in log if e["event"] == "fetch"]
    assert fetches
    assert all(e["outcome"] == "network_error" and e["error"] == "disconnected" for e in fetches)
    assert not (tmp_path / "trip_updates").exists() or not list(
        (tmp_path / "trip_updates").iterdir()
    )


@async_test
async def test_stop_writes_a_final_snapshot_of_buffered_frames(tmp_path: Path) -> None:
    server = FakeMetro(fixture_frames())
    async with fake_metro(server) as url:
        await run_for(make_runner(tmp_path, url), 0.5)  # stop before the first grid cut

    fetches = [e for e in read_log(tmp_path) if e["event"] == "fetch"]
    assert any(e["outcome"] == "written" for e in fetches), (
        "frames since the last cut must be saved"
    )


@async_test
async def test_a_spool_failure_is_logged_and_streaming_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0
    real_write = Spool.write_snapshot

    def flaky_write(self: Spool, snap: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("No space left on device")
        return real_write(self, snap)

    monkeypatch.setattr(Spool, "write_snapshot", flaky_write)
    server = FakeMetro(fixture_frames())
    async with fake_metro(server) as url:
        await run_for(make_runner(tmp_path, url), 2.6)

    outcomes = [e["outcome"] for e in read_log(tmp_path) if e["event"] == "fetch"]
    assert "spool_error" in outcomes
    assert "written" in outcomes[outcomes.index("spool_error") + 1 :], "later cuts still succeed"
    assert server.connections == 1, "a disk error must not drop the connection"
