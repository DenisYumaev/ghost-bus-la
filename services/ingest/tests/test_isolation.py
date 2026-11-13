"""Hard rule 3: ingest depends only on the network, local disk, and S3.

It must keep archiving when Postgres, the API, or a bad deploy of shared code
is broken, so it may not import application code or a database driver. These
tests turn that rule from a sentence in CLAUDE.md into a failing build.
"""

import ast
import re
import tomllib
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = SERVICE_ROOT / "src" / "ghostbus_ingest"

# Top-level modules ingest must never import.
FORBIDDEN_MODULES = frozenset(
    {
        "ghostbus_core",  # shared app code: a bug there must not stop the archive
        "fastapi",
        "sqlalchemy",
        "psycopg",
        "psycopg2",
        "alembic",
        "duckdb",
    }
)


def imported_top_level_modules(source: str) -> set[str]:
    """Return the top-level package of every import statement in `source`."""
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def test_helper_sees_plain_dotted_and_from_imports() -> None:
    source = "\n".join(
        [
            "import os",
            "import sqlalchemy.orm",
            "from ghostbus_core.config import X",
            "from . import y",  # relative: inside ingest itself, allowed
        ]
    )
    assert imported_top_level_modules(source) == {"os", "sqlalchemy", "ghostbus_core"}


def test_source_tree_exists() -> None:
    assert (SOURCE_ROOT / "__init__.py").is_file()


def test_ingest_source_imports_nothing_forbidden() -> None:
    offenders = {
        path.relative_to(SERVICE_ROOT).as_posix(): sorted(
            imported_top_level_modules(path.read_text()) & FORBIDDEN_MODULES
        )
        for path in SOURCE_ROOT.rglob("*.py")
    }
    assert {path: mods for path, mods in offenders.items() if mods} == {}


def test_ingest_declares_no_forbidden_dependency() -> None:
    project = tomllib.loads((SERVICE_ROOT / "pyproject.toml").read_text())["project"]
    # A requirement string starts with the distribution name: "boto3>=1.35; python_version..."
    names = {
        re.split(r"[\s;\[<>=!~]", dep, maxsplit=1)[0].lower().replace("-", "_")
        for dep in project.get("dependencies", [])
    }
    assert names & FORBIDDEN_MODULES == set()


def test_every_third_party_import_is_declared_as_a_dependency() -> None:
    # The production image installs only ingest's own dependencies. A module that is present in
    # the dev environment but undeclared passes every other test and then crashes the container
    # at startup (it happened once: websockets was only in the dev group).
    import sys

    imported: set[str] = set()
    for path in SOURCE_ROOT.rglob("*.py"):
        imported |= imported_top_level_modules(path.read_text())
    third_party = imported - set(sys.stdlib_module_names) - {"ghostbus_ingest"}

    project = tomllib.loads((SERVICE_ROOT / "pyproject.toml").read_text())["project"]
    declared = {
        re.split(r"[\s;\[<>=!~]", dep, maxsplit=1)[0].lower().replace("-", "_")
        for dep in project.get("dependencies", [])
    }
    assert third_party - declared == set(), "declare these in services/ingest/pyproject.toml"
