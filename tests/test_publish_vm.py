"""scripts/publish_vm.py: the password stays out of command lines and output, publish never
talks to anything but the tunnel it opened, and the tunnel always closes."""

import socket
import subprocess
from pathlib import Path
from typing import Any

import publish_vm
import pytest
from publish_vm import LOCAL_PORT, database_url, publish_env, run, tunnel_command

PASSWORD = "fake" + "x" * 28  # obviously fake; no real secret in tests


class FakeSSM:
    def get_parameter(self, Name: str, WithDecryption: bool) -> dict[str, Any]:
        assert Name == "/ghost-bus-la/db/pipeline-password"
        assert WithDecryption
        return {"Parameter": {"Value": PASSWORD}}


class FakeTunnel:
    """Stands in for `aws ssm start-session`: listens on the port unless told to die."""

    def __init__(self, port: int, opens: bool) -> None:
        self.pid = -1
        self.exited = not opens
        self.listener: socket.socket | None = None
        if opens:
            self.listener = socket.socket()
            self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.listener.bind(("127.0.0.1", port))
            self.listener.listen()

    def poll(self) -> int | None:
        return 1 if self.exited else None

    def close(self) -> None:
        if self.listener:
            self.listener.close()


@pytest.fixture
def port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free: int = s.getsockname()[1]
    return free


@pytest.fixture
def closed(monkeypatch: pytest.MonkeyPatch) -> list[FakeTunnel]:
    seen: list[FakeTunnel] = []

    def fake_close(tunnel: FakeTunnel) -> None:
        tunnel.close()
        seen.append(tunnel)

    monkeypatch.setattr(publish_vm, "close_tunnel", fake_close)
    return seen


def launcher(port: int, opens: bool, calls: list[dict[str, Any]]) -> Any:
    def popen(command: list[str], **kwargs: Any) -> FakeTunnel:
        calls.append({"command": command, **kwargs})
        return FakeTunnel(port, opens)

    return popen


def test_publish_runs_through_the_tunnel_and_the_tunnel_closes(
    port: int, closed: list[FakeTunnel]
) -> None:
    tunnel_calls: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []

    def runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        runs.append({"command": command, **kwargs})
        return subprocess.CompletedProcess(command, 0)

    code = run(["--force"], FakeSSM(), "i-0123", Path("."), launcher(port, True, tunnel_calls),
               runner, port=port)  # fmt: skip
    assert code == 0
    assert len(closed) == 1
    # Its own process group, so the plugin child dies with it.
    assert tunnel_calls[0]["start_new_session"] is True
    # The password is only in the publish child's environment.
    assert PASSWORD not in " ".join(tunnel_calls[0]["command"])
    assert "env" not in tunnel_calls[0]
    assert PASSWORD not in " ".join(runs[0]["command"])
    assert PASSWORD in runs[0]["env"]["GHOSTBUS_DATABASE_URL"]
    assert runs[0]["command"][-1] == "--force"


def test_a_taken_port_stops_before_reading_the_password(port: int) -> None:
    class NoSSM:
        def get_parameter(self, **_: Any) -> None:
            raise AssertionError("the password must not be read")

    with socket.socket() as squatter:
        squatter.bind(("127.0.0.1", port))
        squatter.listen()
        assert run([], NoSSM(), "i-0123", Path("."), launcher(port, True, []), port=port) == 1


def test_a_tunnel_that_dies_fails_fast_and_publish_never_runs(
    port: int, closed: list[FakeTunnel], capsys: pytest.CaptureFixture[str]
) -> None:
    def runner(*_: Any, **__: Any) -> None:
        raise AssertionError("publish must not run")

    assert (
        run([], FakeSSM(), "i-0123", Path("."), launcher(port, False, []), runner, port=port) == 1
    )
    assert len(closed) == 1
    assert "session-manager-plugin" in capsys.readouterr().err


def test_the_tunnel_closes_when_publish_raises(port: int, closed: list[FakeTunnel]) -> None:
    def runner(*_: Any, **__: Any) -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run([], FakeSSM(), "i-0123", Path("."), launcher(port, True, []), runner, port=port)
    assert len(closed) == 1


def test_the_tunnel_command_carries_no_secret() -> None:
    command = tunnel_command("i-0123")
    assert "AWS-StartPortForwardingSession" in command
    assert f"portNumber=5432,localPortNumber={LOCAL_PORT}" in command


def test_the_url_is_the_pipeline_role_and_insists_on_scram() -> None:
    env = publish_env(PASSWORD, {"PATH": "/bin"})
    assert env["GHOSTBUS_DATABASE_URL"] == database_url(PASSWORD)
    assert env["GHOSTBUS_DATABASE_URL"].startswith("postgresql+psycopg://pipeline:")
    assert env["GHOSTBUS_DATABASE_URL"].endswith("?require_auth=scram-sha-256")
    assert env["PATH"] == "/bin"
