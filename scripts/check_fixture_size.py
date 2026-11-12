"""Fail if any committed test fixture is larger than 1 MiB.

Fixtures are recorded from real feeds (hard rule 10), and real feeds are big:
one trip-updates cycle is about 3.5 MB. Git keeps every version of every file
forever, so a large fixture slows every clone and CI run from then on. Trim
recordings to the few messages a test needs.

Usage: python scripts/check_fixture_size.py [repo_root]
"""

import sys
from pathlib import Path

MAX_FILE_BYTES = 1024 * 1024
SKIP_DIRS = frozenset({".git", ".venv", "node_modules", ".mypy_cache", ".ruff_cache"})


def find_fixture_dirs(root: Path) -> list[Path]:
    """Every `tests/fixtures` directory under `root`, outside tool and dependency folders."""
    found = []
    for candidate in root.rglob("fixtures"):
        relative_parts = candidate.relative_to(root).parts
        if SKIP_DIRS.intersection(relative_parts):
            continue
        if candidate.is_dir() and candidate.parent.name == "tests":
            found.append(candidate)
    return sorted(found)


def oversized_files(fixture_dirs: list[Path]) -> list[Path]:
    """Files strictly larger than MAX_FILE_BYTES, in a stable order."""
    return sorted(
        path
        for directory in fixture_dirs
        for path in directory.rglob("*")
        if path.is_file() and path.stat().st_size > MAX_FILE_BYTES
    )


def main(root: Path) -> int:
    offenders = oversized_files(find_fixture_dirs(root))
    limit_mib = MAX_FILE_BYTES / (1024 * 1024)
    for path in offenders:
        size_mib = path.stat().st_size / (1024 * 1024)
        print(
            f"{path.relative_to(root).as_posix()}: {size_mib:.1f} MiB exceeds the "
            f"{limit_mib:.1f} MiB fixture limit; trim it to the messages the test needs",
            file=sys.stderr,
        )
    return 1 if offenders else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()))
