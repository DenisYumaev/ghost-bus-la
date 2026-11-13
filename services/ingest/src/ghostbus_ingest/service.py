"""The ingest service: both streams and the uploader in one process (SPEC section 3.2).

Run with `python -m ghostbus_ingest`. Settings come from environment variables:

    GHOSTBUS_BUCKET             data bucket (required)
    GHOSTBUS_SPOOL_DIR          default /var/lib/ghostbus/spool
    GHOSTBUS_FEEDS_CONFIG       default config/feeds.toml
    GHOSTBUS_UPLOAD_INTERVAL_S  default 10
    GHOSTBUS_HEALTH_PORT        default 8081 (GET /healthz on localhost)
    GHOSTBUS_HEARTBEAT_URL      optional; else read from SSM GHOSTBUS_HEARTBEAT_SSM_PARAM
                                (default /ghost-bus-la/heartbeat-url)
    AWS_REGION                  default us-west-2

Credentials come from the standard AWS chain: the VM's instance role in production.

Lifecycle: on SIGTERM or SIGINT (what `docker stop` sends) the streams close, each makes a
final cut, then the uploader makes a final pass that stores the spool and the open fetch-log
hour. If a stream or the uploader crashes, the service still shuts down that way, then exits
with code 1 so Docker restarts it. Logs are JSON lines on stdout (infra spec, section 7).
"""

import asyncio
import os
import signal
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

import boto3
import httpx

from ghostbus_ingest.fetch_log import FetchLog
from ghostbus_ingest.health import FeedHealth, serve_health
from ghostbus_ingest.heartbeat import Heartbeat, resolve_heartbeat_url
from ghostbus_ingest.logs import log_event
from ghostbus_ingest.s3 import S3Client
from ghostbus_ingest.spool import Spool
from ghostbus_ingest.stream import FeedConfig, StreamRunner, load_feeds
from ghostbus_ingest.uploader import Uploader

INGEST_VERSION = version("ghostbus-ingest")
UPLOADER_JOIN_TIMEOUT_S = 60


@dataclass(frozen=True)
class Settings:
    bucket: str
    spool_dir: Path
    feeds_config: Path
    region: str
    upload_interval_s: float
    health_port: int = 8081

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Settings":
        bucket = env.get("GHOSTBUS_BUCKET", "")
        if not bucket:
            raise ValueError("GHOSTBUS_BUCKET must be set to the data bucket name")
        raw_interval = env.get("GHOSTBUS_UPLOAD_INTERVAL_S", "10")
        try:
            interval = float(raw_interval)
        except ValueError:
            interval = -1.0
        if interval <= 0:
            raise ValueError(
                f"GHOSTBUS_UPLOAD_INTERVAL_S must be a positive number (got {raw_interval!r})"
            )
        raw_port = env.get("GHOSTBUS_HEALTH_PORT", "8081")
        if not raw_port.isdigit() or not 0 <= int(raw_port) <= 65535:
            raise ValueError(f"GHOSTBUS_HEALTH_PORT must be a port number (got {raw_port!r})")
        return cls(
            bucket=bucket,
            spool_dir=Path(env.get("GHOSTBUS_SPOOL_DIR", "/var/lib/ghostbus/spool")),
            feeds_config=Path(env.get("GHOSTBUS_FEEDS_CONFIG", "config/feeds.toml")),
            region=env.get("AWS_REGION", "us-west-2"),
            upload_interval_s=interval,
            health_port=int(raw_port),
        )


async def run_service(
    settings: Settings,
    feeds: Mapping[str, FeedConfig],
    s3: S3Client,
    stop: asyncio.Event,
    heartbeat: Heartbeat | None = None,
) -> int:
    """Run until `stop` is set or something crashes. Returns the process exit code."""
    settings.spool_dir.mkdir(parents=True, exist_ok=True)
    spool = Spool(settings.spool_dir)
    fetch_log = FetchLog(settings.spool_dir, INGEST_VERSION)
    # At startup nothing is mid-write, so every temp file is debris from a crash.
    spool.remove_stale_tmp(now=time.time(), older_than_s=0)

    log_event(
        "service_start",
        version=INGEST_VERSION,
        feeds=sorted(feeds),
        heartbeat=heartbeat is not None,
    )
    loop = asyncio.get_running_loop()
    crashed = False

    health = FeedHealth({f.name: f.interval_s for f in feeds.values()}, started_at=time.time())
    health_server = await serve_health(health, "127.0.0.1", settings.health_port)
    fastest = min(feeds.values(), key=lambda f: f.interval_s).name
    pings: set[asyncio.Task[bool]] = set()  # keep references so tasks aren't garbage-collected

    def on_result(feed: str, outcome: str, at: float) -> None:
        health.record(feed, outcome, at)
        # One ping per cycle of the fastest feed, and only while *every* feed is healthy.
        if heartbeat is not None and feed == fastest and health.is_healthy(at):
            task = asyncio.create_task(heartbeat.ping())
            pings.add(task)
            task.add_done_callback(pings.discard)

    uploader = Uploader(spool, fetch_log, s3, settings.bucket)
    uploader_stop = threading.Event()

    def run_uploader() -> None:
        nonlocal crashed
        try:
            uploader.run(uploader_stop, interval_s=settings.upload_interval_s)
        except Exception as error:  # a bug: stop everything so Docker restarts us
            crashed = True
            log_event("uploader_crashed", error=repr(error))
            loop.call_soon_threadsafe(stop.set)

    uploader_thread = threading.Thread(target=run_uploader, name="uploader")
    uploader_thread.start()

    async def run_stream(feed: FeedConfig) -> None:
        nonlocal crashed
        try:
            await StreamRunner(feed, spool, fetch_log, on_result=on_result).run(stop)
        except Exception as error:
            crashed = True
            log_event("stream_crashed", feed=feed.name, error=repr(error))
            stop.set()

    await asyncio.gather(*(run_stream(feed) for feed in feeds.values()))
    health_server.close()
    await health_server.wait_closed()
    if pings:
        await asyncio.wait(pings, timeout=15)

    # Streams have made their final cuts; now the uploader's final pass stores everything.
    uploader_stop.set()
    await asyncio.to_thread(uploader_thread.join, UPLOADER_JOIN_TIMEOUT_S)
    if uploader_thread.is_alive():
        crashed = True
        log_event("uploader_stuck", timeout_s=UPLOADER_JOIN_TIMEOUT_S)

    code = 1 if crashed else 0
    log_event("service_stop", exit_code=code)
    return code


async def _main_async(
    settings: Settings, feeds: Mapping[str, FeedConfig], s3: S3Client, heartbeat_url: str | None
) -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    async with httpx.AsyncClient() as client:
        heartbeat = Heartbeat(heartbeat_url, client) if heartbeat_url else None
        return await run_service(settings, feeds, s3, stop, heartbeat)


def main() -> int:
    try:
        settings = Settings.from_env(os.environ)
        feeds = load_feeds(settings.feeds_config)
    except (ValueError, OSError) as error:
        log_event("config_error", error=str(error))
        return 2

    s3 = boto3.client("s3", region_name=settings.region)
    ssm = boto3.client("ssm", region_name=settings.region)
    heartbeat_url = resolve_heartbeat_url(os.environ, ssm)
    return asyncio.run(_main_async(settings, feeds, s3, heartbeat_url))


if __name__ == "__main__":
    sys.exit(main())
