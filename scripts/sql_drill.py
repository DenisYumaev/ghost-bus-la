"""SQL drills against a synthetic copy of the warehouse (learning spec section 4).

    sql_drill.py list        every problem and whether you passed it
    sql_drill.py start 03    copy the starter to attempts/ and start the clock
    sql_drill.py check 03    run your attempt and the reference; compare
    sql_drill.py schema      every practice table with three sample rows
    sql_drill.py build       write data/sql-practice.duckdb for the duckdb shell

(The Makefile wraps these: make sql-drill [P=03], make sql-check P=03, make sql-shell.)

Each check builds the practice data fresh in memory from practice_data.sql,
so an attempt can't damage anything and the answer never drifts. Results are
compared as multisets of rows (column names ignored) unless the problem says
"Order: checked". Floats match within 0.001, so rounding to three decimals
the other way still passes. Times and passes go to docs/learning/sql-log.md.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DRILLS = ROOT / "docs" / "learning" / "sql"
PROBLEMS = DRILLS / "problems"
SOLUTIONS = DRILLS / "solutions"
ATTEMPTS = DRILLS / "attempts"
STATE = ATTEMPTS / ".state.json"
LOG = ROOT / "docs" / "learning" / "sql-log.md"
PRACTICE_DB = ROOT / "data" / "sql-practice.duckdb"
FLOAT_TOLERANCE = 1e-3 + 1e-9
SHOW = 3

Row = tuple[Any, ...]


@dataclass(frozen=True)
class Result:
    passed: bool
    message: str


def practice_connection() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    con.execute((DRILLS / "practice_data.sql").read_text())
    return con


def find(directory: Path, key: str) -> Path:
    number = f"{int(key):02d}" if key.isdigit() else key
    matches = sorted(directory.glob(f"{number}-*.sql"))
    if len(matches) != 1:
        raise SystemExit(f"no single problem matches {key!r} in {directory.relative_to(ROOT)}")
    return matches[0]


def is_ordered(problem: Path) -> bool:
    return "-- Order: checked" in problem.read_text()


def run(con: duckdb.DuckDBPyConnection, sql: str) -> list[Row]:
    relation = con.sql(sql)
    if relation is None:
        raise ValueError("the file has no SELECT that returns rows")
    return [tuple(row) for row in relation.fetchall()]


def _normalize(value: Any) -> Any:
    """Make a value hashable and put every number on one scale."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | Decimal):
        return float(value)
    if isinstance(value, list | tuple):
        return tuple(_normalize(v) for v in value)
    if isinstance(value, dict):
        return tuple(sorted((str(k), _normalize(v)) for k, v in value.items()))
    return value


def _split(row: Row) -> tuple[Row, tuple[float, ...]]:
    """Separate a row into exact-match values and numbers (compared within tolerance)."""
    exact: list[Any] = []
    numbers: list[float] = []
    for value in map(_normalize, row):
        if isinstance(value, float) and math.isnan(value):
            exact.append("<nan>")
        elif isinstance(value, float):
            numbers.append(value)
            exact.append("<number>")
        else:
            exact.append(value)
    return tuple(exact), tuple(numbers)


def _same(a: Row, b: Row) -> bool:
    exact_a, floats_a = _split(a)
    exact_b, floats_b = _split(b)
    return exact_a == exact_b and all(
        math.isclose(x, y, abs_tol=FLOAT_TOLERANCE) for x, y in zip(floats_a, floats_b, strict=True)
    )


def compare(expected: list[Row], actual: list[Row], *, ordered: bool) -> Result:
    if expected and actual and len(expected[0]) != len(actual[0]):
        return Result(False, f"expected {len(expected[0])} columns, got {len(actual[0])}")
    if ordered:
        for i, (e, a) in enumerate(zip(expected, actual, strict=False)):
            if not _same(e, a):
                return Result(False, f"row {i + 1} differs (or is out of order): got {a}")
        if len(expected) != len(actual):
            return Result(False, f"expected {len(expected)} rows, got {len(actual)}")
        return Result(True, f"{len(actual)} rows, in order")

    # Bucket by the exact-match part, then pair floats within tolerance.
    # Sorting both sides by their numbers first keeps greedy pairing from
    # spending a close match on the wrong row.
    buckets: dict[Row, list[Row]] = defaultdict(list)
    for row in sorted(expected, key=lambda r: _split(r)[1]):
        buckets[_split(row)[0]].append(row)
    extra: list[Row] = []
    for row in sorted(actual, key=lambda r: _split(r)[1]):
        candidates = buckets.get(_split(row)[0], [])
        match = next((i for i, e in enumerate(candidates) if _same(e, row)), None)
        if match is None:
            extra.append(row)
        else:
            candidates.pop(match)
    missing = [row for rows in buckets.values() for row in rows]
    if not extra and not missing:
        return Result(True, f"{len(actual)} rows match")
    lines = [f"expected {len(expected)} rows, got {len(actual)}"]
    if extra:
        lines.append(f"{len(extra)} of your rows aren't in the answer, e.g.:")
        lines += [f"    {row}" for row in extra[:SHOW]]
    if missing:
        lines.append(f"{len(missing)} answer rows are missing from yours")
    return Result(False, "\n".join(lines))


def check_sql(sql: str, solution: Path, *, ordered: bool) -> Result:
    con = practice_connection()
    expected = run(con, solution.read_text())
    try:
        actual = run(con, sql)
    except (duckdb.Error, ValueError) as exc:
        return Result(False, f"your query failed: {exc}")
    return compare(expected, actual, ordered=ordered)


def load_state() -> dict[str, Any]:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save_state(state: dict[str, Any]) -> None:
    ATTEMPTS.mkdir(exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    tmp.replace(STATE)  # atomic: an interrupted write never leaves half a file


def cmd_list() -> None:
    state = load_state()
    for problem in sorted(PROBLEMS.glob("*.sql")):
        entry = state.get(problem.stem, {})
        if entry.get("passed"):
            mark = "pass"
        elif entry.get("ever_passed"):
            mark = "redo"
        else:
            mark = "tried" if entry.get("checks") else ""
        title = problem.read_text().splitlines()[0].removeprefix("-- ")
        print(f"  {mark:>5}  {title}")


def cmd_start(key: str) -> None:
    problem = find(PROBLEMS, key)
    attempt = ATTEMPTS / problem.name
    ATTEMPTS.mkdir(exist_ok=True)
    # Every start is a clean, timed run: an earlier answer left in the file
    # would pass at once and log a time that isn't real (hard rule 11).
    if attempt.exists() and attempt.read_text() != problem.read_text():
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        backup = attempt.with_name(f"{attempt.stem}.{stamp}.bak")
        attempt.replace(backup)
        print(f"Your previous attempt is saved as {backup.relative_to(ROOT)}")
    attempt.write_text(problem.read_text())
    state = load_state()
    previous = state.get(problem.stem, {})
    state[problem.stem] = {
        "started": datetime.now(UTC).isoformat(),
        "checks": 0,
        "passed": False,
        "ever_passed": previous.get("ever_passed", False) or previous.get("passed", False),
    }
    save_state(state)
    print(f"Clock started. Write your query in {attempt.relative_to(ROOT)}")
    print(f"then: make sql-check P={key}")


def cmd_check(key: str) -> int:
    problem = find(PROBLEMS, key)
    attempt = ATTEMPTS / problem.name
    if not attempt.exists():
        raise SystemExit(f"start it first: make sql-drill P={key}")
    result = check_sql(attempt.read_text(), find(SOLUTIONS, key), ordered=is_ordered(problem))
    state = load_state()
    entry = state.setdefault(problem.stem, {"checks": 0, "passed": False})
    entry["checks"] = entry.get("checks", 0) + 1
    print(("PASS  " if result.passed else "NOT YET  ") + result.message)
    if result.passed and not entry.get("passed"):
        entry["passed"] = True
        entry["ever_passed"] = True
        minutes = None
        if "started" in entry:
            elapsed = datetime.now(UTC) - datetime.fromisoformat(entry["started"])
            minutes = round(elapsed.total_seconds() / 60)
        log_pass(problem.stem, minutes, entry["checks"])
        shown = f"{minutes} min, " if minutes is not None else ""
        reference = find(SOLUTIONS, key).relative_to(ROOT)
        print(f"{shown}{entry['checks']} checks. Compare with {reference}")
    save_state(state)
    return 0 if result.passed else 1


def log_pass(stem: str, minutes: int | None, checks: int) -> None:
    if not LOG.exists():
        LOG.write_text(
            "# SQL drill log\n\nWritten by `make sql-check` on a first pass. "
            "Targets are in each problem's header.\n\n"
            "| Date | Problem | Minutes | Checks |\n| --- | --- | --- | --- |\n"
        )
    shown = "" if minutes is None else str(minutes)
    with LOG.open("a") as f:
        f.write(f"| {datetime.now(UTC).date()} | {stem} | {shown} | {checks} |\n")


def cmd_schema() -> None:
    con = practice_connection()
    tables = [
        row[0] for row in con.sql("SELECT table_name FROM duckdb_tables() ORDER BY 1").fetchall()
    ]
    for table in tables:
        relation = con.table(table)  # a table object, not SQL text: no injection surface
        print(f"\n{table}  ({len(relation.fetchall())} rows)")
        print(relation.limit(3))


def cmd_build() -> None:
    PRACTICE_DB.parent.mkdir(exist_ok=True)
    PRACTICE_DB.unlink(missing_ok=True)
    con = duckdb.connect(str(PRACTICE_DB))
    con.execute((DRILLS / "practice_data.sql").read_text())
    con.close()
    path = PRACTICE_DB.relative_to(ROOT)
    print(f"wrote {path}; open it with: duckdb {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=["list", "start", "check", "schema", "build"])
    parser.add_argument("problem", nargs="?", help="problem number, e.g. 03")
    args = parser.parse_args(argv)
    if args.command in {"start", "check"} and not args.problem:
        parser.error(f"{args.command} needs a problem number")
    if args.command == "list":
        cmd_list()
    elif args.command == "start":
        cmd_start(args.problem)
    elif args.command == "check":
        return cmd_check(args.problem)
    elif args.command == "schema":
        cmd_schema()
    else:
        cmd_build()
    return 0


if __name__ == "__main__":
    sys.exit(main())
