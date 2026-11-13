"""The external heartbeat (pipeline spec, section 2.6; infra spec, section 9).

Ingest pings a Healthchecks.io URL while it is healthy. If the pings stop for 3 minutes (a dead
VM, a crash loop, or a stream that stopped producing snapshots), Healthchecks alerts the owner.
The check lives outside AWS, so it still works when the VM is gone.

The ping URL is a secret: anyone holding it could send false "all good" pings. It comes from
SSM Parameter Store (or an environment variable for local runs) and is never logged.
A missing URL disables the heartbeat with a log line; it never stops ingest (hard rule 3).
"""

import asyncio
from collections.abc import Mapping
from typing import Any

import httpx
from botocore.exceptions import BotoCoreError, ClientError

from ghostbus_ingest.logs import log_event

DEFAULT_SSM_PARAM = "/ghost-bus-la/heartbeat-url"


def resolve_heartbeat_url(env: Mapping[str, str], ssm: Any) -> str | None:
    """GHOSTBUS_HEARTBEAT_URL if set, else the SSM parameter. None disables the heartbeat."""
    url = env.get("GHOSTBUS_HEARTBEAT_URL")
    source = "env"
    if not url:
        name = env.get("GHOSTBUS_HEARTBEAT_SSM_PARAM", DEFAULT_SSM_PARAM)
        source = f"ssm:{name}"
        try:
            url = ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
        except (ClientError, BotoCoreError) as error:
            log_event("heartbeat_disabled", source=source, error=type(error).__name__)
            return None
    if not url or not url.startswith("https://"):
        log_event("heartbeat_disabled", source=source, error="URL must start with https://")
        return None
    return url


class Heartbeat:
    def __init__(self, url: str, client: httpx.AsyncClient, timeout_s: float = 10.0) -> None:
        self._url = url
        self._client = client
        self._timeout_s = timeout_s

    async def ping(self) -> bool:
        """GET the ping URL. Returns success; never raises (a ping must not hurt ingest)."""
        try:
            response = await asyncio.wait_for(self._client.get(self._url), self._timeout_s)
        except (httpx.HTTPError, TimeoutError) as error:
            log_event("heartbeat_failed", error=type(error).__name__)
            return False
        if response.status_code >= 400:
            log_event("heartbeat_failed", status=response.status_code)
            return False
        return True
