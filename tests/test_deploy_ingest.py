"""Tests for scripts/deploy_ingest.py: the laptop side of an ingest deploy.

SSM is replayed with botocore's Stubber and GHCR with httpx.MockTransport, so nothing here
reaches AWS or the network. The VM side (deploy/remote-deploy-ingest.sh) is exercised by real
deploys and the M2 failed-deploy drill.
"""

import base64
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import boto3
import httpx
import pytest
from botocore.stub import ANY, Stubber
from deploy_ingest import build_commands, deploy, image_exists

SHA = "dd166b2524d2dde37e662e7e024a2bfe29f88474"
REPO = Path(__file__).resolve().parents[1]


def ghcr(status: int) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(200, json={"token": "anon"})
        assert request.headers["Authorization"] == "Bearer anon"
        assert request.url.path.endswith(f"/manifests/{SHA}")
        return httpx.Response(status)

    return httpx.Client(transport=httpx.MockTransport(handler))


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
        stub.assert_no_pending_responses()


def test_image_exists_checks_ghcr_anonymously_like_the_vm_will() -> None:
    assert image_exists(SHA, ghcr(200)) is True
    assert image_exists(SHA, ghcr(404)) is False


def test_commands_carry_the_compose_file_and_run_the_remote_script() -> None:
    commands = build_commands(SHA, "the-bucket", REPO)

    exported = commands[0]
    assert f"SHA={SHA}" in exported
    assert "BUCKET=the-bucket" in exported
    compose_b64 = exported.split("COMPOSE_B64=")[1].split()[0]
    assert base64.b64decode(compose_b64) == (REPO / "deploy/compose.ingest.yml").read_bytes()
    assert commands[-1] == "bash /tmp/ghost-bus-la-deploy.sh"


@pytest.mark.parametrize("bad", ["main", "dd166b2", SHA.upper(), SHA + "0", "x; rm -rf /"])
def test_only_a_full_lowercase_sha_is_accepted(bad: str, ssm: tuple[Any, Stubber]) -> None:
    client, _stub = ssm  # nothing queued: any SSM call would fail the test
    with pytest.raises(ValueError, match="SHA"):
        deploy(bad, "i-0123", "bucket", REPO, client, ghcr(200), poll_s=0)


def test_a_missing_image_aborts_before_touching_the_vm(ssm: tuple[Any, Stubber]) -> None:
    client, _stub = ssm
    with pytest.raises(RuntimeError, match="not published"):
        deploy(SHA, "i-0123", "bucket", REPO, client, ghcr(404), poll_s=0)


def test_successful_deploy_returns_the_vm_output(ssm: tuple[Any, Stubber]) -> None:
    client, stub = ssm
    stub.add_response(
        "send_command",
        {"Command": {"CommandId": "11111111-2222-3333-4444-555555555555"}},
        {
            "InstanceIds": ["i-0123"],
            "DocumentName": "AWS-RunShellScript",
            "Comment": f"ghost-bus-la ingest deploy {SHA[:12]}",
            "Parameters": {"commands": ANY, "executionTimeout": ["900"]},
        },
    )
    stub.add_client_error("get_command_invocation", "InvocationDoesNotExist", http_status_code=400)
    stub.add_response(
        "get_command_invocation",
        {"Status": "InProgress", "StandardOutputContent": "", "StandardErrorContent": ""},
        {"CommandId": "11111111-2222-3333-4444-555555555555", "InstanceId": "i-0123"},
    )
    stub.add_response(
        "get_command_invocation",
        {
            "Status": "Success",
            "StandardOutputContent": f"RESULT: deployed {SHA}\n",
            "StandardErrorContent": "",
        },
        {"CommandId": "11111111-2222-3333-4444-555555555555", "InstanceId": "i-0123"},
    )

    ok, output = deploy(SHA, "i-0123", "bucket", REPO, client, ghcr(200), poll_s=0)

    assert ok is True
    assert f"RESULT: deployed {SHA}" in output


def test_failed_deploy_reports_failure_with_the_vm_output(ssm: tuple[Any, Stubber]) -> None:
    client, stub = ssm
    stub.add_response(
        "send_command", {"Command": {"CommandId": "66666666-7777-8888-9999-000000000000"}}, None
    )
    stub.add_response(
        "get_command_invocation",
        {
            "Status": "Failed",
            "StandardOutputContent": "RESULT: rolled back to abc\n",
            "StandardErrorContent": "",
        },
        {"CommandId": "66666666-7777-8888-9999-000000000000", "InstanceId": "i-0123"},
    )

    ok, output = deploy(SHA, "i-0123", "bucket", REPO, client, ghcr(200), poll_s=0)

    assert ok is False
    assert "rolled back" in output
