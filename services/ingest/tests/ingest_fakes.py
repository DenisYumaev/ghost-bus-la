"""Shared test doubles for ingest: a fake Metro WebSocket server and a fake S3.

Imported by the ingest tests (pytest's `pythonpath` includes this directory). Nothing here
touches the network beyond localhost, or AWS (hard rule 10).
"""

import asyncio
import functools
import gzip
import json
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError
from websockets.asyncio.server import ServerConnection, serve

FIXTURES = Path(__file__).parent / "fixtures"


def async_test(fn: Callable[..., Coroutine[Any, Any, None]]) -> Callable[..., None]:
    """Run an async test with asyncio.run, so no pytest plugin is needed."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> None:
        asyncio.run(fn(*args, **kwargs))

    return wrapper


def fixture_frames(name: str = "trip_updates_45s.jsonl.gz") -> list[bytes]:
    with gzip.open(FIXTURES / name, "rt") as f:
        return [json.loads(line)["raw"].encode() for line in f]


class FakeMetro:
    """Replays frames in a loop like Metro does; records what clients sent and when."""

    def __init__(self, frames: list[bytes], drop_after: int | None = None) -> None:
        self.frames = frames
        self.drop_after = drop_after  # close the first connection after this many frames
        self.connections = 0
        self.max_concurrent = 0
        self.active = 0
        self.user_agents: list[str] = []

    async def handler(self, ws: ServerConnection) -> None:
        self.connections += 1
        self.active += 1
        self.max_concurrent = max(self.max_concurrent, self.active)
        self.user_agents.append(ws.request.headers.get("User-Agent", "") if ws.request else "")
        try:
            sent = 0
            while True:
                for frame in self.frames:
                    await ws.send(frame, text=True)  # a text frame, as Metro sends
                    sent += 1
                    if (
                        self.connections == 1
                        and self.drop_after is not None
                        and sent >= self.drop_after
                    ):
                        await ws.close(code=1011, reason="server restarting")
                        return
                    await asyncio.sleep(0.001)
        finally:
            self.active -= 1


@asynccontextmanager
async def fake_metro(server: FakeMetro) -> AsyncIterator[str]:
    async with serve(server.handler, "127.0.0.1", 0) as ws_server:
        port = next(iter(ws_server.sockets)).getsockname()[1]
        yield f"ws://127.0.0.1:{port}"


def iso(stamp: str) -> float:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


def read_log(root: Path) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for path in sorted((root / "_fetch_log").rglob("*.jsonl")):
        lines += [json.loads(line) for line in path.read_text().splitlines()]
    return lines


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
