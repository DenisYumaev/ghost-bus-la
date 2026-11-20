"""Runs deploy/remote-deploy-app.sh under bash with fake docker, aws, snap and curl on PATH, so
the VM-side failure handling is tested offline: a failed step fails the deploy, and a rollback
never re-runs migrations (the old image wouldn't know the new revision)."""

import base64
import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "deploy/remote-deploy-app.sh"
NEW = "a" * 40
OLD = "b" * 40

# Behavior comes from the environment: FAIL_ON=<compose subcommand> fails that call; READYZ is
# what the API's readiness check prints; every call is appended to $CALLS.
FAKE_DOCKER = r"""#!/usr/bin/env bash
echo "$*" >> "$CALLS"
sub=""
for a in "$@"; do case "$a" in pull|up|run|exec|ps|logs|inspect) sub=$a; break ;; esac; done
[ -n "${FAIL_ON:-}" ] && [ "$sub" = "$FAIL_ON" ] && exit 1
case "$sub" in
  inspect) echo healthy ;;
  ps) echo container-id ;;
  exec) echo "${READYZ:-Serving data is stale}" ;;
esac
exit 0
"""
FAKE_AWS = (
    '#!/usr/bin/env bash\n[ -n "${EMPTY_SECRET:-}" ] && exit 0\necho "s3cr3t-$RANDOM-value"\n'
)
FAKE_OK = "#!/usr/bin/env bash\necho 200\n"


def run(
    tmp_path: Path, previous: str | None = None, **env: str
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in {
        "docker": FAKE_DOCKER,
        "aws": FAKE_AWS,
        "snap": FAKE_OK,
        "curl": FAKE_OK,
    }.items():
        path = bin_dir / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    app = tmp_path / "app"
    app.mkdir(exist_ok=True)
    if previous:
        (app / "api.tag").write_text(previous + "\n")
    full_env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}", "CALLS": str(tmp_path / "calls"),
        "APP_DIR": str(app), "HEALTH_WAIT_S": "2", "POLL_S": "1", "SHA": NEW,
        "API_DOMAIN": "api.example.test", "SITE_DOMAIN": "example.test",
        "COMPOSE_B64": base64.b64encode(b"services: {}\n").decode(),
        "CADDY_B64": base64.b64encode(b"example.test {}\n").decode(), **env,
    }  # fmt: skip
    return subprocess.run(  # noqa: S603 - fixed script path
        ["bash", str(SCRIPT)],  # noqa: S607 - bash from PATH, like the VM's SSM runner
        env=full_env,
        capture_output=True,
        text=True,
        check=False,
    )


def calls(tmp_path: Path, sub: str) -> list[str]:
    return [c for c in (tmp_path / "calls").read_text().splitlines() if f" {sub} " in f" {c} "]


def test_a_good_deploy_records_the_sha_and_keeps_secrets_out_of_the_output(tmp_path: Path) -> None:
    result = run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "app/api.tag").read_text().strip() == NEW
    env_file = tmp_path / "app/.env"
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    assert "s3cr3t" in env_file.read_text()
    assert "s3cr3t" not in result.stdout + result.stderr
    assert "TLS check https://api.example.test/healthz: 200" in result.stdout


def test_a_failed_migration_fails_the_deploy_before_the_api_starts(tmp_path: Path) -> None:
    result = run(tmp_path, FAIL_ON="run")
    assert result.returncode == 1
    assert "migrate failed" in result.stdout
    assert not (tmp_path / "app/api.tag").exists()
    assert not [c for c in calls(tmp_path, "up") if " api " in f" {c} "]


@pytest.mark.parametrize("fail_on", ["pull", "up"])
def test_any_failed_step_fails_the_deploy(tmp_path: Path, fail_on: str) -> None:
    result = run(tmp_path, previous=OLD, FAIL_ON=fail_on)
    assert result.returncode == 1
    assert (tmp_path / "app/api.tag").read_text().strip() == OLD


def test_an_unready_api_rolls_back_without_migrating(tmp_path: Path) -> None:
    result = run(tmp_path, previous=OLD, READYZ="Database unavailable")
    assert result.returncode == 1
    assert f"rolling back to {OLD} (no migration)" in result.stdout
    # One migrate, for the new SHA only.
    assert len(calls(tmp_path, "run")) == 1
    assert (tmp_path / "app/api.tag").read_text().strip() == OLD


def test_an_empty_secret_stops_the_deploy(tmp_path: Path) -> None:
    result = run(tmp_path, EMPTY_SECRET="1")  # noqa: S106 - a flag, not a secret
    assert result.returncode == 1
    assert "make init-secrets" in result.stdout
    assert not calls(tmp_path, "pull")
