"""Deploy ingest to the VM over SSM. The laptop side; the VM side is deploy/remote-deploy-ingest.sh.

    uv run python scripts/deploy_ingest.py <full git sha>      (or: make deploy-ingest SHA=...)

1. Refuse anything but a full 40-character git SHA: a deploy names exactly one image build.
2. Check that the image is published and pullable anonymously, exactly as the VM will pull it.
3. Send the remote script, the compose file, the SHA, and the bucket through SSM Run Command.
   Nothing travels over SSH; the VM has no inbound ports.
4. Wait for the result and print the VM's output. The remote script waits for Docker to report
   the container healthy and rolls back to the previous SHA if it doesn't.

Credentials: the configured AWS profile (hard rule 9). The instance ID and bucket come from
`terraform output`, so nothing account-specific is committed.
"""

import base64
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import boto3
import httpx
from botocore.exceptions import ClientError

IMAGE_REPO = "denisyumaev/ghost-bus-la-ingest"
REMOTE_SCRIPT_PATH = "/tmp/ghost-bus-la-deploy.sh"  # noqa: S108 - on the VM, written by root
_SHA = re.compile(r"^[0-9a-f]{40}$")
_MANIFEST_TYPES = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)


def image_exists(sha: str, http: httpx.Client) -> bool:
    """True if ghcr.io serves the manifest for this tag without credentials."""
    token = http.get(
        "https://ghcr.io/token", params={"scope": f"repository:{IMAGE_REPO}:pull"}
    ).json()["token"]
    response = http.get(
        f"https://ghcr.io/v2/{IMAGE_REPO}/manifests/{sha}",
        headers={"Authorization": f"Bearer {token}", "Accept": _MANIFEST_TYPES},
    )
    return response.status_code == 200


def build_commands(sha: str, bucket: str, repo_root: Path) -> list[str]:
    """The SSM RunShellScript lines. They run as one script, so the export carries through."""
    compose = base64.b64encode((repo_root / "deploy/compose.ingest.yml").read_bytes()).decode()
    remote = base64.b64encode((repo_root / "deploy/remote-deploy-ingest.sh").read_bytes()).decode()
    return [
        f"export SHA={sha} BUCKET={bucket} COMPOSE_B64={compose}",
        f"echo {remote} | base64 -d > {REMOTE_SCRIPT_PATH}",
        f"bash {REMOTE_SCRIPT_PATH}",
    ]


def deploy(
    sha: str,
    instance_id: str,
    bucket: str,
    repo_root: Path,
    ssm: Any,
    http: httpx.Client,
    poll_s: float = 5.0,
) -> tuple[bool, str]:
    """Run the deploy; return (succeeded, the VM's output)."""
    if not _SHA.match(sha):
        raise ValueError(f"deploy needs a full 40-character lowercase git SHA, got {sha!r}")
    if not image_exists(sha, http):
        raise RuntimeError(f"image ghcr.io/{IMAGE_REPO}:{sha} is not published (or not public)")

    command_id = ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Comment=f"ghost-bus-la ingest deploy {sha[:12]}",
        Parameters={
            "commands": build_commands(sha, bucket, repo_root),
            "executionTimeout": ["900"],
        },
    )["Command"]["CommandId"]

    while True:
        time.sleep(poll_s)
        try:
            result = ssm.get_command_invocation(CommandId=command_id, InstanceId=instance_id)
        except ClientError as error:
            if error.response["Error"]["Code"] == "InvocationDoesNotExist":
                continue  # SSM hasn't registered the invocation yet
            raise
        if result["Status"] not in ("Pending", "InProgress", "Delayed"):
            output = result["StandardOutputContent"] + result["StandardErrorContent"]
            return result["Status"] == "Success", output


def _terraform_output(repo_root: Path, name: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed arguments, no shell
        ["terraform", f"-chdir={repo_root / 'infra'}", "output", "-raw", name],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    repo_root = Path(__file__).resolve().parents[1]
    instance_id = _terraform_output(repo_root, "instance_id")
    bucket = _terraform_output(repo_root, "data_bucket_name")
    ssm = boto3.client("ssm", region_name="us-west-2")
    with httpx.Client(timeout=30) as http:
        ok, output = deploy(argv[0], instance_id, bucket, repo_root, ssm, http)
    print(output)
    print("DEPLOY SUCCEEDED" if ok else "DEPLOY FAILED (see output above)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
