"""The GTFS schedule download (pipeline spec, sections 2.2, 2.3, and 4; ADR-021 decision 6).

Metro publishes its bus schedule as one ZIP in a GitLab repository. Ingest fetches it on start
and daily at 03:00 Los Angeles time. A ZIP whose bytes changed is a new **schedule version**:
it goes to the spool exactly as downloaded, and the uploader stores it at
`bronze/gtfs_static/dt=YYYY-MM-DD/<sha16>.zip` with a conditional write, like every snapshot.
An unchanged ZIP is logged as `duplicate` and not stored again.

Failures never stop the streams: the schedule changes about weekly, the streams are the data
that can't be recovered (hard rule 3). A network error, a 5xx or 429, or a body that isn't a ZIP
is retried with the shared backoff, at most MAX_RETRIES times in a row; any other 4xx (the file
moved) waits for the next daily slot, because retrying wouldn't help and would hammer someone
else's server. An unexpected exception is logged and treated as a failure, never raised.
"""

import asyncio
import contextlib
import hashlib
import io
import random
import re
import time
import tomllib
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from ghostbus_ingest.backoff import backoff_delay
from ghostbus_ingest.fetch_log import FetchLog, Outcome
from ghostbus_ingest.logs import log_event
from ghostbus_ingest.spool import Spool, SpoolResult

FEED = "gtfs_static"
URL_KEY = "gtfs_bus_gitlab"
TIMEOUT_S = 120.0  # spec 2.3
MAX_BYTES = 64 * 1024 * 1024  # the ZIP is about 22 MB; the body is held in memory (mem_limit 512m)
MAX_RETRIES = 10  # then wait for the next daily slot instead of asking every minute
LA = ZoneInfo("America/Los_Angeles")
_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


@dataclass(frozen=True)
class GtfsConfig:
    url: str
    daily_at: str  # "HH:MM", Los Angeles local time


def load_gtfs(path: Path) -> GtfsConfig | None:
    """Read `[gtfs_static]` from config/feeds.toml. No section means no download."""
    raw = tomllib.loads(path.read_text()).get("gtfs_static")
    if raw is None:
        return None
    url, daily_at = raw.get("url", ""), raw.get("daily_at", "")
    if not url.startswith("https://"):
        raise ValueError(f"gtfs_static: url must start with https:// (got {url!r})")
    if not _HHMM.match(daily_at):
        raise ValueError(f"gtfs_static: daily_at must be HH:MM, 24-hour (got {daily_at!r})")
    return GtfsConfig(url, daily_at)


def next_daily_run(now: float, daily_at: str) -> float:
    """The next `daily_at` in Los Angeles strictly after `now`, as a UTC timestamp.

    Built from the local calendar date, so it stays at 03:00 local across daylight-saving
    changes instead of drifting to 02:00 or 04:00.
    """
    hour, minute = (int(x) for x in daily_at.split(":"))
    local = datetime.fromtimestamp(now, tz=LA)
    candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate.timestamp() <= now:
        day = (local + timedelta(days=1)).date()
        candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=LA)
    return candidate.timestamp()


class _TooLarge(Exception):
    pass


class GtfsDownloader:
    def __init__(
        self, config: GtfsConfig, spool: Spool, fetch_log: FetchLog, client: httpx.AsyncClient
    ) -> None:
        self.config = config
        self.spool = spool
        self.fetch_log = fetch_log
        self.client = client
        self.max_bytes = MAX_BYTES
        self.last_status: int | None = None  # of the latest attempt; None if it never got one

    async def _get(self) -> tuple[int, bytearray]:
        """GET the ZIP within TIMEOUT_S in total. Stops reading just past max_bytes.

        httpx's own timeout applies to each step (connect, each read), so a server trickling
        bytes could hold a download open forever; asyncio.timeout bounds the whole request.
        """
        async with asyncio.timeout(TIMEOUT_S):
            async with self.client.stream("GET", self.config.url) as response:
                declared = response.headers.get("Content-Length", "")
                if declared.isdigit() and int(declared) > self.max_bytes:
                    raise _TooLarge(f"Content-Length {declared} exceeds {self.max_bytes}")
                body = bytearray()  # returned as is: no second copy of up to 64 MB
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > self.max_bytes:
                        raise _TooLarge(f"body larger than {self.max_bytes} bytes")
                return response.status_code, body

    async def download_once(self, now: float) -> str:
        """One attempt. Returns the outcome it logged."""
        started = time.monotonic()
        self.last_status = None
        try:
            status, body = await self._get()
        except _TooLarge as error:
            self.fetch_log.record_download(now, FEED, URL_KEY, "http_error", error=str(error))
            return "http_error"
        except (httpx.HTTPError, TimeoutError) as error:
            self.fetch_log.record_download(now, FEED, URL_KEY, "network_error", error=repr(error))
            return "network_error"
        self.last_status = status
        latency_ms = round((time.monotonic() - started) * 1000)
        seen = Seen(status, latency_ms, len(body))

        # Hashing, the ZIP check, and the fsynced write of ~22 MB run in a thread so the
        # streams' event loop isn't blocked.
        return await asyncio.to_thread(self._store, now, bytes(body), seen)

    def _store(self, now: float, body: bytes, seen: "Seen") -> str:
        sha = hashlib.sha256(body).hexdigest()
        if seen.status != 200:
            return self._log(now, "http_error", seen, sha, f"HTTP {seen.status}")
        if not zipfile.is_zipfile(io.BytesIO(body)):
            return self._log(now, "http_error", seen, sha, "body is not a ZIP")
        try:
            result = self.spool.write_file(FEED, now, body, sha)
        except OSError as error:  # a full disk: log it, try again later
            return self._log(now, "spool_error", seen, sha, repr(error))
        return self._log(now, result.outcome, seen, sha, None, result)

    def _log(
        self,
        now: float,
        outcome: Outcome,
        seen: "Seen",
        sha: str,
        error: str | None,
        result: SpoolResult | None = None,
    ) -> str:
        self.fetch_log.record_download(
            now, FEED, URL_KEY, outcome, result=result, http_status=seen.status,
            latency_ms=seen.latency_ms, body_len=seen.size, sha256=sha, error=error,
        )  # fmt: skip
        return outcome

    @staticmethod
    def should_retry(outcome: str, http_status: int | None) -> bool:
        """Retry soon, or wait for the next daily slot?"""
        if outcome in ("written", "duplicate"):
            return False
        if outcome == "http_error" and http_status is not None and 400 <= http_status < 500:
            return http_status == 429  # rate limited: back off; any other 4xx won't fix itself
        return True

    async def _attempt(self, stop: asyncio.Event, now: float) -> str | None:
        """One download, cancelled if `stop` is set first (None). Never raises a bug."""
        download = asyncio.create_task(self.download_once(now))
        stopping = asyncio.create_task(stop.wait())
        await asyncio.wait({download, stopping}, return_when=asyncio.FIRST_COMPLETED)
        stopping.cancel()
        if not download.done():
            download.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await download
            return None
        try:
            return download.result()
        except Exception as error:  # a bug: log it, count it as a failure, keep going
            log_event("gtfs_error", error=repr(error))
            return "error"

    async def run(
        self,
        stop: asyncio.Event,
        clock: Callable[[], float] = time.time,
        wait: Callable[[float], Awaitable[object]] | None = None,
        rand: Callable[[], float] = random.random,
    ) -> None:
        """Download on start, then daily at `daily_at`, until `stop` is set."""

        async def sleep_or_stop(seconds: float) -> None:
            with contextlib.suppress(TimeoutError):  # timed out: time for the next attempt
                await asyncio.wait_for(stop.wait(), timeout=seconds)

        pause = wait if wait is not None else sleep_or_stop
        failures = 0
        while not stop.is_set():
            outcome = await self._attempt(stop, clock())
            if outcome is None:
                break
            retry = self.should_retry(outcome, self.last_status)
            if retry and failures < MAX_RETRIES - 1:
                delay = backoff_delay(failures, rand=rand)
                failures += 1
            else:
                failures = 0
                now = clock()
                delay = next_daily_run(now, self.config.daily_at) - now
            log_event("gtfs_next", outcome=outcome, in_s=round(delay, 1))
            if stop.is_set():
                break
            await pause(delay)


@dataclass(frozen=True)
class Seen:
    """What the server sent: status, time to the full body, and its size."""

    status: int
    latency_ms: int
    size: int


__all__ = ["GtfsConfig", "GtfsDownloader", "load_gtfs", "next_daily_run"]
