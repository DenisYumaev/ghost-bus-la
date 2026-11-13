"""Ingest health: is every feed producing snapshots? (pipeline spec, section 2.6)

Healthy means every feed had a successful cut (`written` or `duplicate`) within three of its
intervals. Until a feed's first success, the service start time stands in, which gives a
startup grace period of three intervals.

`/healthz` on a local port serves this for Docker's health check; the heartbeat pings only
while it holds, so a dead VM *or* a dead stream raises the external alert.
"""

import asyncio
import json
import time
from collections.abc import Callable, Mapping
from typing import Any

HEALTHY_INTERVALS = 3
SUCCESS_OUTCOMES = frozenset({"written", "duplicate"})


class FeedHealth:
    def __init__(self, intervals: Mapping[str, int], started_at: float) -> None:
        self.intervals = dict(intervals)
        self._last_success = dict.fromkeys(self.intervals, started_at)

    def record(self, feed: str, outcome: str, at: float) -> None:
        if outcome in SUCCESS_OUTCOMES and feed in self._last_success:
            self._last_success[feed] = max(self._last_success[feed], at)

    def report(self, now: float) -> dict[str, dict[str, Any]]:
        return {
            feed: {
                "seconds_since_success": round(now - self._last_success[feed], 1),
                "limit_s": HEALTHY_INTERVALS * interval,
                "healthy": now - self._last_success[feed] <= HEALTHY_INTERVALS * interval,
            }
            for feed, interval in self.intervals.items()
        }

    def is_healthy(self, now: float) -> bool:
        return all(entry["healthy"] for entry in self.report(now).values())


async def serve_health(
    health: FeedHealth, host: str, port: int, clock: Callable[[], float] = time.time
) -> asyncio.Server:
    """A minimal HTTP server: GET /healthz gives 200 or 503 with a JSON body; else 404.

    Bound to localhost inside the container; nothing outside the VM can reach it.
    """

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=5)
            parts = request_line.decode("latin-1").split()
            path = parts[1] if len(parts) >= 2 else ""
            if path == "/healthz":
                now = clock()
                ok = health.is_healthy(now)
                status = "200 OK" if ok else "503 Service Unavailable"
                body = {"status": "ok" if ok else "unhealthy", "feeds": health.report(now)}
            else:
                status, body = "404 Not Found", {"error": "not found"}
            payload = json.dumps(body).encode()
            writer.write(
                f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode()
                + payload
            )
            await writer.drain()
        except (TimeoutError, ConnectionError):
            pass
        finally:
            writer.close()

    return await asyncio.start_server(handle, host, port)
