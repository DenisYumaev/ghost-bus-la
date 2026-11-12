"""Tests for scripts/check_fixture_size.py, run by `make lint` and CI.

Fixtures are committed to git, and git keeps every version forever, so one
careless 50 MB recording bloats every clone for the life of the repo.
"""

from pathlib import Path

import pytest
from check_fixture_size import MAX_FILE_BYTES, find_fixture_dirs, main, oversized_files


def _write(path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def test_limit_is_one_mebibyte() -> None:
    assert MAX_FILE_BYTES == 1024 * 1024


def test_finds_root_and_per_service_fixture_dirs(tmp_path: Path) -> None:
    _write(tmp_path / "tests/fixtures/a.json", 1)
    _write(tmp_path / "services/ingest/tests/fixtures/b.json", 1)
    _write(tmp_path / "services/ingest/src/not_a_fixture.json", 1)

    dirs = find_fixture_dirs(tmp_path)

    assert sorted(d.relative_to(tmp_path).as_posix() for d in dirs) == [
        "services/ingest/tests/fixtures",
        "tests/fixtures",
    ]


def test_ignores_virtualenv_and_git_dirs(tmp_path: Path) -> None:
    _write(tmp_path / ".venv/lib/pkg/tests/fixtures/big.bin", 1)
    _write(tmp_path / ".git/tests/fixtures/big.bin", 1)
    _write(tmp_path / "node_modules/x/tests/fixtures/big.bin", 1)

    assert find_fixture_dirs(tmp_path) == []


def test_file_at_limit_passes_and_one_byte_over_fails(tmp_path: Path) -> None:
    fixtures = tmp_path / "tests/fixtures"
    _write(fixtures / "at_limit.ndjson.gz", MAX_FILE_BYTES)
    over = _write(fixtures / "nested/over.ndjson.gz", MAX_FILE_BYTES + 1)

    assert oversized_files([fixtures]) == [over]


def test_main_returns_zero_when_clean(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(tmp_path / "tests/fixtures/small.json", 10)

    assert main(tmp_path) == 0
    assert capsys.readouterr().err == ""


def test_main_returns_one_and_names_each_offender(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(tmp_path / "tests/fixtures/huge.ndjson", MAX_FILE_BYTES + 1)

    assert main(tmp_path) == 1
    err = capsys.readouterr().err
    assert "tests/fixtures/huge.ndjson" in err
    assert "1.0 MiB" in err
