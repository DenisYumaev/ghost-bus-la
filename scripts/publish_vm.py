"""Publish the laptop's dbt warehouse into the VM's Postgres, as the `pipeline` role (M2).

    uv run python scripts/publish_vm.py [publish args...]      (or: make publish-vm ARGS=...)

dbt runs on the laptop until the pipeline moves to the VM (M4), so this carries its output:
1. read the pipeline password from SSM (/ghost-bus-la/db/pipeline-password) with the configured
   AWS profile;
2. open an SSM port-forwarding session to the VM's loopback Postgres (no inbound port is open);
3. run `python -m ghostbus_publish` with GHOSTBUS_DATABASE_URL in its environment only;
4. close the session.

The password is never printed or put on a command line. Needs the AWS Session Manager plugin.
"""

import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import boto3
from deploy_ingest import terraform_output

LOCAL_PORT = 15432
PARAMETER = "/ghost-bus-la/db/pipeline-password"


def database_url(password: str, port: int = LOCAL_PORT) -> str:
    # token_urlsafe passwords need no escaping in a URL. require_auth refuses any server that
    # doesn't do SCRAM, so the password never crosses the wire in cleartext, even to a wrong one.
    return (
        f"postgresql+psycopg://pipeline:{password}@127.0.0.1:{port}/ghostbus"
        "?require_auth=scram-sha-256"
    )


def tunnel_command(instance_id: str, port: int = LOCAL_PORT) -> list[str]:
    return [
        "aws", "ssm", "start-session", "--region", "us-west-2", "--target", instance_id,
        "--document-name", "AWS-StartPortForwardingSession",
        "--parameters", f"portNumber=5432,localPortNumber={port}",
    ]  # fmt: skip


def port_is_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def wait_for_tunnel(tunnel: Any, port: int, timeout_s: float = 30.0) -> bool:
    """True once the port accepts connections; False if the tunnel process exits first."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if tunnel.poll() is not None:
            return False
        with socket.socket() as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.5)
    return False


def close_tunnel(tunnel: Any) -> None:
    """Stop the whole process group: `aws` starts session-manager-plugin as a child, and a
    SIGTERM to `aws` alone would leave the plugin listening and the session open."""
    try:
        os.killpg(tunnel.pid, signal.SIGTERM)
        tunnel.wait(timeout=10)
    except ProcessLookupError:
        return
    except subprocess.TimeoutExpired:
        os.killpg(tunnel.pid, signal.SIGKILL)


def publish_env(password: str, base: dict[str, str]) -> dict[str, str]:
    return {**base, "GHOSTBUS_DATABASE_URL": database_url(password)}


def run(
    argv: Sequence[str],
    ssm: Any,
    instance_id: str,
    repo_root: Path,
    popen: Callable[..., Any] = subprocess.Popen,
    runner: Callable[..., Any] = subprocess.run,
    port: int = LOCAL_PORT,
) -> int:
    if not port_is_free(port):
        # Something else listens there (an old tunnel, a local Postgres): never send it
        # the password.
        print(f"port {port} is in use; close whatever holds it and retry", file=sys.stderr)
        return 1
    password = ssm.get_parameter(Name=PARAMETER, WithDecryption=True)["Parameter"]["Value"]
    tunnel = popen(
        tunnel_command(instance_id, port), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,  # its own process group, so close_tunnel stops the plugin too
    )  # fmt: skip
    try:
        if not wait_for_tunnel(tunnel, port):
            print(
                "the SSM tunnel didn't open (is session-manager-plugin installed? has "
                "`make deploy-app` published Postgres on the VM's loopback?)",
                file=sys.stderr,
            )
            return 1
        return int(
            runner(
                [sys.executable, "-m", "ghostbus_publish", *argv],
                env=publish_env(password, dict(os.environ)), cwd=repo_root, check=False,
            ).returncode
        )  # fmt: skip
    finally:
        close_tunnel(tunnel)


def main(argv: list[str]) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    instance_id = terraform_output(repo_root, "instance_id")
    return run(argv, boto3.client("ssm", region_name="us-west-2"), instance_id, repo_root)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
