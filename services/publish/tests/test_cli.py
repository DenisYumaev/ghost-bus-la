"""The publish CLI and the migrate entry point never print the database URL (hard rule 9):
libpq's parse errors quote the URL, password included."""

import json
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

SENTINEL = "s3cr3t-SENTINEL"
# A bad percent-escape in the password makes libpq refuse the URI and quote the password in its
# error ('invalid percent-encoded token: "..."'), checked by hand with psycopg 3.
BAD_URL = f"postgresql://ghostbus:{SENTINEL}%zz@localhost:5432/ghostbus"


def run(module: str, tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed interpreter and module
        [sys.executable, "-m", module, *args],
        env={"GHOSTBUS_DATABASE_URL": BAD_URL, "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, check=False, cwd=tmp_path, timeout=60,
    )  # fmt: skip


def test_publish_does_not_print_the_password(tmp_path: Path) -> None:
    duckdb.connect(str(tmp_path / "w.duckdb")).close()  # a valid, empty warehouse
    sync = tmp_path / "sync.json"
    sync.write_text(json.dumps({"start": "2026-11-15", "end": "2026-11-16"}))
    result = run("ghostbus_publish", tmp_path, "--warehouse", "w.duckdb", "--sync-file", str(sync))
    assert result.returncode != 0
    assert "details withheld" in result.stderr  # it got as far as connecting
    assert SENTINEL not in result.stdout + result.stderr


@pytest.mark.parametrize("module", ["ghostbus_api.migrations"])
def test_migrate_does_not_print_the_password(tmp_path: Path, module: str) -> None:
    result = run(module, tmp_path)
    assert result.returncode != 0
    assert "details withheld" in result.stderr
    assert SENTINEL not in result.stdout + result.stderr
