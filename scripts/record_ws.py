"""Record a Metro WebSocket stream to a local file, for test fixtures and analysis.

One connection, for a fixed number of seconds, then it disconnects. Each received frame is
written as one JSON line: {"t": seconds since connect, "raw": "<frame text, unchanged>"}.
The raw text is stored as a JSON string, so its exact characters survive the round trip.

This is a development tool, not part of ingest: it writes to a local path you choose,
never to S3. Keep recordings out of git; trim them with scripts/trim_ws_fixture.py.

Usage:
    uv run python scripts/record_ws.py trip_updates 45 /path/to/out.jsonl
"""

import asyncio
import json
import sys
import time
from pathlib import Path

from websockets.asyncio.client import connect

STREAMS = frozenset({"vehicle_positions", "trip_updates"})
URL = "wss://api.metro.net/ws/LACMTA/{stream}"
# ADR-021: identify the project; the repo is the contact route, no personal email.
USER_AGENT = "ghost-bus-la/0.1 (+https://github.com/DenisYumaev/ghost-bus-la)"


async def record(stream: str, seconds: float, out: Path) -> int:
    if stream not in STREAMS:
        raise ValueError(f"unknown stream {stream!r}; expected one of {sorted(STREAMS)}")
    count = 0
    async with connect(URL.format(stream=stream), user_agent_header=USER_AGENT) as ws:
        start = time.monotonic()
        with out.open("w") as f:
            while (remaining := seconds - (time.monotonic() - start)) > 0:
                try:
                    frame = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except TimeoutError:
                    break
                text = frame if isinstance(frame, str) else frame.decode("utf-8")
                line = {"t": round(time.monotonic() - start, 4), "raw": text}
                f.write(json.dumps(line) + "\n")
                count += 1
    return count


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    stream, seconds, out = argv[0], float(argv[1]), Path(argv[2])
    n = asyncio.run(record(stream, seconds, out))
    print(f"{stream}: {n} frames in {seconds:.0f} s -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
