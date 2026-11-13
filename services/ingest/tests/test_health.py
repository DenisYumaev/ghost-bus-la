"""Tests for ingest health: the per-feed rule, the /healthz endpoint, and the heartbeat.

Pipeline spec section 2.6: healthy when every feed succeeded within three of its intervals; an
external heartbeat pinged while healthy, so a dead VM or a dead stream both raise an alert.
"""

import asyncio
import json
from collections.abc import Iterator
from typing import Any

import boto3
import httpx
import pytest
from botocore.stub import Stubber
from ghostbus_ingest.health import FeedHealth, serve_health
from ghostbus_ingest.heartbeat import Heartbeat, resolve_heartbeat_url
from ingest_fakes import async_test

INTERVALS = {"vehicle_positions": 30, "trip_updates": 60}
T0 = 1_000_000.0

# --- the rule ------------------------------------------------------------------------------------


def test_healthy_during_the_startup_grace_period() -> None:
    health = FeedHealth(INTERVALS, started_at=T0)
    assert health.is_healthy(T0 + 89)  # 3 x 30 s for the faster feed
    assert not health.is_healthy(T0 + 91)


def test_each_feed_needs_a_success_within_three_of_its_intervals() -> None:
    health = FeedHealth(INTERVALS, started_at=T0)
    health.record("vehicle_positions", "written", T0 + 100)
    health.record("trip_updates", "duplicate", T0 + 100)  # a duplicate is a success

    assert health.is_healthy(T0 + 189)
    assert not health.is_healthy(T0 + 191)  # vehicle positions: 91 s > 90 s
    report = health.report(T0 + 191)
    assert report["vehicle_positions"]["healthy"] is False
    assert report["trip_updates"]["healthy"] is True  # 91 s < 180 s


@pytest.mark.parametrize("outcome", ["network_error", "spool_error"])
def test_failures_do_not_count_as_success(outcome: str) -> None:
    health = FeedHealth(INTERVALS, started_at=T0)
    health.record("vehicle_positions", outcome, T0 + 80)
    health.record("trip_updates", "written", T0 + 80)
    assert not health.is_healthy(T0 + 95)


# --- /healthz ------------------------------------------------------------------------------------


@async_test
async def test_healthz_returns_200_when_healthy_and_503_when_not() -> None:
    now = [T0 + 10.0]
    health = FeedHealth(INTERVALS, started_at=T0)
    server = await serve_health(health, "127.0.0.1", 0, clock=lambda: now[0])
    port = server.sockets[0].getsockname()[1]
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
            ok = await client.get("/healthz")
            now[0] = T0 + 500
            bad = await client.get("/healthz")
            missing = await client.get("/other")
    finally:
        server.close()
        await server.wait_closed()

    assert ok.status_code == 200
    assert ok.json()["status"] == "ok"
    assert bad.status_code == 503
    assert bad.json()["status"] == "unhealthy"
    assert bad.json()["feeds"]["trip_updates"]["healthy"] is False
    assert missing.status_code == 404


# --- heartbeat -----------------------------------------------------------------------------------


@async_test
async def test_ping_sends_a_get_to_the_heartbeat_url() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="OK")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ok = await Heartbeat("https://hc-ping.com/abc", client).ping()

    assert ok is True
    assert [str(r.url) for r in seen] == ["https://hc-ping.com/abc"]


@pytest.mark.parametrize("failure", ["status", "network"])
@async_test
async def test_a_failed_ping_never_raises(failure: str, capsys: pytest.CaptureFixture[str]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "network":
            raise httpx.ConnectError("no route", request=request)
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        ok = await Heartbeat("https://hc-ping.com/abc", client).ping()

    assert ok is False
    logged = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert logged[-1]["event"] == "heartbeat_failed"
    assert "hc-ping.com/abc" not in json.dumps(logged), "the ping URL is a secret; never log it"


# --- resolving the URL ---------------------------------------------------------------------------


@pytest.fixture
def ssm() -> Iterator[tuple[Any, Stubber]]:
    client = boto3.client(
        "ssm",
        region_name="us-west-2",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",  # noqa: S106 - deliberately fake; Stubber blocks network
    )
    with Stubber(client) as stub:
        yield client, stub


def test_env_url_wins_and_ssm_is_not_called(ssm: tuple[Any, Stubber]) -> None:
    client, _stub = ssm  # no responses queued: any call would fail
    env = {"GHOSTBUS_HEARTBEAT_URL": "https://hc-ping.com/env"}
    assert resolve_heartbeat_url(env, client) == "https://hc-ping.com/env"


def test_url_is_read_from_ssm_with_decryption(ssm: tuple[Any, Stubber]) -> None:
    client, stub = ssm
    stub.add_response(
        "get_parameter",
        {"Parameter": {"Name": "/ghost-bus-la/heartbeat-url", "Value": "https://hc-ping.com/ssm"}},
        {"Name": "/ghost-bus-la/heartbeat-url", "WithDecryption": True},
    )
    assert resolve_heartbeat_url({}, client) == "https://hc-ping.com/ssm"


def test_missing_parameter_disables_the_heartbeat_but_never_blocks_ingest(
    ssm: tuple[Any, Stubber], capsys: pytest.CaptureFixture[str]
) -> None:
    client, stub = ssm
    stub.add_client_error("get_parameter", "ParameterNotFound", http_status_code=400)

    assert resolve_heartbeat_url({}, client) is None
    [line] = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert line["event"] == "heartbeat_disabled"


def test_a_non_https_url_is_rejected(ssm: tuple[Any, Stubber]) -> None:
    client, _stub = ssm
    assert resolve_heartbeat_url({"GHOSTBUS_HEARTBEAT_URL": "http://hc-ping.com/x"}, client) is None


@async_test
async def test_heartbeat_ping_has_a_timeout() -> None:
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as client:
        start = asyncio.get_running_loop().time()
        ok = await Heartbeat("https://hc-ping.com/abc", client, timeout_s=0.2).ping()
        elapsed = asyncio.get_running_loop().time() - start

    assert ok is False
    assert elapsed < 1.0
