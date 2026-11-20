"""Tests for scripts/deploy_app.py and scripts/init_secrets.py (laptop side). SSM is replayed with
botocore's Stubber and GHCR with httpx.MockTransport: nothing reaches AWS or the network."""

import base64
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import boto3
import httpx
import pytest
from botocore.stub import ANY, Stubber
from deploy_app import API_REPO, build_commands, deploy
from init_secrets import NAMES, PREFIX, ensure

SHA = "dd166b2524d2dde37e662e7e024a2bfe29f88474"
REPO = Path(__file__).resolve().parents[1]
CMD = "11111111-2222-3333-4444-555555555555"  # SSM validates the command ID's length


def ghcr(status: int) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            assert request.url.params["scope"] == f"repository:{API_REPO}:pull"
            return httpx.Response(200, json={"token": "anon"})
        assert request.url.path == f"/v2/{API_REPO}/manifests/{SHA}"
        return httpx.Response(status)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def ssm() -> Iterator[tuple[Any, Stubber]]:
    client = boto3.client(
        "ssm", region_name="us-west-2",
        aws_access_key_id="testing", aws_secret_access_key="testing",  # noqa: S106 - fake
    )  # fmt: skip
    with Stubber(client) as stub:
        yield client, stub


def test_commands_carry_the_files_and_no_secret() -> None:
    commands = build_commands(SHA, REPO)
    exported = commands[0]
    assert f"SHA={SHA}" in exported
    assert "API_DOMAIN=api.labusreliability.com" in exported
    compose_b64 = exported.split("COMPOSE_B64=")[1].split()[0]
    assert base64.b64decode(compose_b64) == (REPO / "deploy/compose.app.yml").read_bytes()
    # SSM keeps command history: no password, and the remote script reads them itself.
    assert "PASSWORD" not in " ".join(commands)
    remote = (REPO / "deploy/remote-deploy-app.sh").read_text()
    assert "aws ssm get-parameter" in remote
    assert "--with-decryption" in remote


def test_a_missing_image_aborts_before_touching_the_vm(ssm: tuple[Any, Stubber]) -> None:
    client, _ = ssm  # no stubbed responses: any SSM call would fail the test
    with pytest.raises(RuntimeError, match="not published"):
        deploy(SHA, "i-0123", REPO, client, ghcr(404), poll_s=0)


@pytest.mark.parametrize("bad", ["main", SHA[:12], SHA.upper(), SHA + "\n"])
def test_only_a_full_lowercase_sha_is_accepted(bad: str, ssm: tuple[Any, Stubber]) -> None:
    client, _ = ssm
    with pytest.raises(ValueError, match="40-character"):
        deploy(bad, "i-0123", REPO, client, ghcr(200), poll_s=0)


def test_successful_deploy_returns_the_vm_output(ssm: tuple[Any, Stubber]) -> None:
    client, stub = ssm
    stub.add_response("send_command", {"Command": {"CommandId": CMD}}, {
        "InstanceIds": ["i-0123"], "DocumentName": "AWS-RunShellScript", "Comment": ANY,
        "Parameters": ANY,
    })  # fmt: skip
    stub.add_response("get_command_invocation", {
        "Status": "Success", "StandardOutputContent": "RESULT: deployed\n",
        "StandardErrorContent": "",
    }, {"CommandId": CMD, "InstanceId": "i-0123"})  # fmt: skip
    ok, output = deploy(SHA, "i-0123", REPO, client, ghcr(200), poll_s=0)
    assert ok
    assert "RESULT: deployed" in output


def test_init_secrets_creates_only_missing_parameters(ssm: tuple[Any, Stubber]) -> None:
    client, stub = ssm
    for name in NAMES:
        params = {"Name": PREFIX + name, "Value": ANY, "Type": "SecureString",
                  "Overwrite": False, "Description": ANY}  # fmt: skip
        if name == "owner-password":
            stub.add_client_error("put_parameter", "ParameterAlreadyExists", expected_params=params)
        else:
            stub.add_response("put_parameter", {"Version": 1}, params)
    assert ensure(client) == [PREFIX + "api-password", PREFIX + "pipeline-password"]
