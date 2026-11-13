"""One long-lived WebSocket connection per feed, feeding a SnapshotBuffer (spec 2.3, ADR-021).

Two coroutines share one buffer in one event loop (so no locks are needed):

- the connection loop holds the connection, passes each frame's exact bytes to the buffer,
  logs every connect and disconnect, and reconnects with exponential backoff and jitter;
- the cut loop wakes on the wall-clock grid, cuts a snapshot, writes it to the spool, and logs
  the attempt.

On stop, the connection closes and one last snapshot saves the frames received since the
previous cut. A spool failure (a full disk) is logged and the stream keeps running.
"""

import asyncio
import contextlib
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidURI

from ghostbus_ingest.backoff import backoff_delay
from ghostbus_ingest.fetch_log import FetchLog
from ghostbus_ingest.snapshot import Snapshot, SnapshotBuffer, next_grid_point
from ghostbus_ingest.spool import FEEDS, Spool

# ADR-021: name the project; the repository is the contact route, no personal email.
USER_AGENT = (
    f"ghost-bus-la/{version('ghostbus-ingest')} (+https://github.com/DenisYumaev/ghost-bus-la)"
)
OPEN_TIMEOUT_S = 30


@dataclass(frozen=True)
class FeedConfig:
    name: str
    url: str
    interval_s: int


def load_feeds(path: Path) -> dict[str, FeedConfig]:
    """Read config/feeds.toml. URLs live there, never in code (pipeline spec, section 1)."""
    raw = tomllib.loads(path.read_text())
    feeds: dict[str, FeedConfig] = {}
    for name, entry in raw.get("feeds", {}).items():
        if name not in FEEDS:
            raise ValueError(f"unknown feed {name!r} in {path}; expected one of {sorted(FEEDS)}")
        url, interval = entry["url"], entry["interval_s"]
        if not url.startswith("wss://"):
            raise ValueError(f"feed {name!r}: url must start with wss:// (got {url!r})")
        if not isinstance(interval, int) or interval <= 0 or 3600 % interval:
            raise ValueError(
                f"feed {name!r}: interval_s must be whole seconds that divide an hour "
                f"(got {interval!r})"
            )
        feeds[name] = FeedConfig(name, url, interval)
    return feeds


class StreamRunner:
    def __init__(
        self,
        feed: FeedConfig,
        spool: Spool,
        fetch_log: FetchLog,
        clock: Callable[[], float] = time.time,
        backoff: Callable[[int], float] = backoff_delay,
    ) -> None:
        self.feed = feed
        self.spool = spool
        self.fetch_log = fetch_log
        self.clock = clock
        self.backoff = backoff
        start = clock()
        self.buffer = SnapshotBuffer(
            feed.name,
            feed.interval_s,
            interval_start=next_grid_point(start, feed.interval_s) - feed.interval_s,
        )

    async def run(self, stop: asyncio.Event) -> None:
        cutter = asyncio.create_task(self._cut_loop(stop))
        try:
            await self._connection_loop(stop)
        finally:
            stop.set()
            await cutter

    # --- cutting ---------------------------------------------------------------------------

    async def _cut_loop(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            at = next_grid_point(self.clock(), self.feed.interval_s)
            try:
                await asyncio.wait_for(stop.wait(), timeout=max(0.0, at - self.clock()))
                break  # stopping: fall through to the final cut
            except TimeoutError:
                self._cut(at)
        self._cut(max(self.clock(), self.buffer.interval_start))

    def _cut(self, at: float) -> None:
        cut = self.buffer.cut(at)
        if not isinstance(cut, Snapshot):
            self.fetch_log.record_fetch(cut, None)
            return
        try:
            result = self.spool.write_snapshot(cut)
        except OSError as error:
            self.fetch_log.record_fetch(cut, None, error=repr(error))
            return
        self.fetch_log.record_fetch(cut, result)

    # --- connection ------------------------------------------------------------------------

    async def _connection_loop(self, stop: asyncio.Event) -> None:
        attempt = 0
        while not stop.is_set():
            connected = False
            close_code: int | None = None
            reason: str | None = None
            try:
                async with connect(
                    self.feed.url, user_agent_header=USER_AGENT, open_timeout=OPEN_TIMEOUT_S
                ) as ws:
                    connected = True
                    attempt = 0
                    now = self.clock()
                    self.buffer.on_connect(now)
                    self.fetch_log.record_connection(self.feed.name, "connect", now)
                    await self._receive(ws, stop)
            except ConnectionClosed as closed:
                frame = closed.rcvd or closed.sent
                close_code = frame.code if frame else None
                reason = frame.reason if frame else None
            except (OSError, InvalidHandshake, InvalidURI, TimeoutError) as error:
                reason = repr(error)

            now = self.clock()
            if connected:
                self.buffer.on_disconnect(now)
                self.fetch_log.record_connection(
                    self.feed.name, "disconnect", now, close_code=close_code, reason=reason
                )
            else:
                self.fetch_log.record_connection(
                    self.feed.name, "connect_failed", now, reason=reason
                )
            if stop.is_set():
                break
            delay = self.backoff(attempt)
            attempt += 1
            with contextlib.suppress(TimeoutError):  # waking early on stop is the point
                await asyncio.wait_for(stop.wait(), timeout=delay)

    async def _receive(self, ws: ClientConnection, stop: asyncio.Event) -> None:
        """Read frames until the connection closes; close it ourselves when asked to stop."""

        async def close_on_stop() -> None:
            await stop.wait()
            await ws.close(code=1000, reason="ingest shutting down")

        closer = asyncio.create_task(close_on_stop())
        try:
            while True:
                frame = await ws.recv(decode=False)  # the frame's exact bytes, never re-encoded
                self.buffer.on_message(bytes(frame), self.clock())
        finally:
            closer.cancel()
