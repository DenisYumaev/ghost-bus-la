"""Deploy the API stack (Postgres, API, Caddy) to the VM over SSM. The VM side is
deploy/remote-deploy-app.sh.

    uv run python scripts/deploy_app.py <full git sha>      (or: make deploy-app SHA=...)

Same shape as the ingest deploy: refuse anything but a full SHA, check the API image is
published and pullable anonymously, send the compose file, Caddyfile and remote script through
SSM Run Command, and print the VM's output. The remote script reads the database passwords
from SSM itself, so no secret is in the command (SSM keeps command history). Run
scripts/init_secrets.py once before the first deploy.

Credentials: the configured AWS profile (hard rule 9). The instance ID comes from
`terraform output`; the domains are public names.
"""

import base64
import sys
from pathlib import Path
from typing import Any

import boto3
import httpx
from deploy_ingest import _SHA, image_exists, run_on_vm, terraform_output

API_REPO = "denisyumaev/ghost-bus-la-api"
API_DOMAIN = "api.labusreliability.com"
SITE_DOMAIN = "labusreliability.com"
REMOTE_SCRIPT_PATH = "/tmp/ghost-bus-la-deploy-app.sh"  # noqa: S108 - on the VM, written by root


def _b64(repo_root: Path, path: str) -> str:
    return base64.b64encode((repo_root / path).read_bytes()).decode()


def build_commands(sha: str, repo_root: Path) -> list[str]:
    """The SSM RunShellScript lines. They run as one script, so the export carries through."""
    compose = _b64(repo_root, "deploy/compose.app.yml")
    caddy = _b64(repo_root, "deploy/Caddyfile")
    remote = _b64(repo_root, "deploy/remote-deploy-app.sh")
    return [
        f"export SHA={sha} API_DOMAIN={API_DOMAIN} SITE_DOMAIN={SITE_DOMAIN}"
        f" COMPOSE_B64={compose} CADDY_B64={caddy}",
        f"echo {remote} | base64 -d > {REMOTE_SCRIPT_PATH}",
        f"bash {REMOTE_SCRIPT_PATH}",
    ]


def deploy(
    sha: str, instance_id: str, repo_root: Path, ssm: Any, http: httpx.Client, poll_s: float = 5.0
) -> tuple[bool, str]:
    if not _SHA.fullmatch(sha):
        raise ValueError(f"deploy needs a full 40-character lowercase git SHA, got {sha!r}")
    if not image_exists(sha, http, API_REPO):
        raise RuntimeError(f"image ghcr.io/{API_REPO}:{sha} is not published (or not public)")
    return run_on_vm(
        ssm, instance_id, build_commands(sha, repo_root), f"ghost-bus-la app deploy {sha[:12]}",
        poll_s,
    )  # fmt: skip


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    repo_root = Path(__file__).resolve().parents[1]
    instance_id = terraform_output(repo_root, "instance_id")
    ssm = boto3.client("ssm", region_name="us-west-2")
    with httpx.Client(timeout=30) as http:
        ok, output = deploy(argv[0], instance_id, repo_root, ssm, http)
    print(output)
    print("DEPLOY SUCCEEDED" if ok else "DEPLOY FAILED (see output above)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
