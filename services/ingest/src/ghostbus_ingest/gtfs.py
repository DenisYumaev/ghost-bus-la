"""The GTFS schedule download (pipeline spec, sections 2.2, 2.3, and 4; ADR-021 decision 6).

Metro publishes its bus schedule as one ZIP in a GitLab repository. Ingest fetches it on start
and daily at 03:00 Los Angeles time. A ZIP whose bytes changed is a new **schedule version**:
it goes to the spool exactly as downloaded, and the uploader stores it at
`bronze/gtfs_static/dt=YYYY-MM-DD/<sha16>.zip` with a conditional write, like every snapshot.
An unchanged ZIP is logged as `duplicate` and not stored again.

Failures never stop the streams. A network error, a 5xx or 429, or a body that isn't a ZIP is
retried with the shared backoff; any other 4xx (the file moved) waits for the next daily slot,
because retrying every minute wouldn't help and would hammer someone else's server.
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
from ghostbus_ingest.fetch_log import FetchLog
from ghostbus_ingest.logs import log_event
from ghostbus_ingest.spool import Spool

FEED = "gtfs_static"
URL_KEY = "gtfs_bus_gitlab"
TIMEOUT_S = 120.0  # spec 2.3
MAX_BYTES = 200 * 1024 * 1024  # the ZIP is about 22 MB; refuse anything absurd (mem_limit 512m)
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

    async def _get(self) -> tuple[int, bytes]:
        """GET the ZIP, reading at most max_bytes + 1 so an oversized body is caught early."""
        async with self.client.stream("GET", self.config.url, timeout=TIMEOUT_S) as response:
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > self.max_bytes:
                    break
            return response.status_code, bytes(body)

    async def download_once(self, now: float) -> str:
        """One attempt. Returns the outcome it logged."""
        started = time.monotonic()
        self.last_status = None
        try:
            status, body = await self._get()
        except httpx.HTTPError as error:
            self.fetch_log.record_download(now, FEED, URL_KEY, "network_error", error=repr(error))
            return "network_error"
        self.last_status = status
        latency_ms = round((time.monotonic() - started) * 1000)

        problem = None
        if status != 200:
            problem = f"HTTP {status}"
        elif len(body) > self.max_bytes:
            problem = f"body larger than {self.max_bytes} bytes"
        elif not zipfile.is_zipfile(io.BytesIO(body)):
            problem = "body is not a ZIP"  # an error page served with 200
        sha = hashlib.sha256(body).hexdigest()
        if problem:
            self.fetch_log.record_download(
                now, FEED, URL_KEY, "http_error",
                http_status=status, latency_ms=latency_ms, body_len=len(body),
                sha256=sha, error=problem,
            )  # fmt: skip
            return "http_error"

        try:
            result = self.spool.write_file(FEED, now, body, sha)
        except OSError as error:  # a full disk: log it, try again later
            self.fetch_log.record_download(
                now, FEED, URL_KEY, "spool_error",
                http_status=status, latency_ms=latency_ms, body_len=len(body),
                sha256=sha, error=repr(error),
            )  # fmt: skip
            return "spool_error"
        self.fetch_log.record_download(
            now, FEED, URL_KEY, result.outcome, result=result,
            http_status=status, latency_ms=latency_ms, body_len=len(body), sha256=sha,
        )  # fmt: skip
        return result.outcome

    @staticmethod
    def should_retry(outcome: str, http_status: int | None) -> bool:
        """Retry soon, or wait for the next daily slot?"""
        if outcome in ("written", "duplicate"):
            return False
        if outcome == "http_error" and http_status is not None and 400 <= http_status < 500:
            return http_status == 429  # rate limited: back off; any other 4xx won't fix itself
        return True

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
            outcome = await self.download_once(clock())
            if self.should_retry(outcome, self.last_status):
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


__all__ = ["GtfsConfig", "GtfsDownloader", "load_gtfs", "next_daily_run"]
