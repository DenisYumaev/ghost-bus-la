"""The SQL drill checker: reference answers run, traps fail, comparison is fair."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
import sql_drill as drill

PROBLEMS = sorted(drill.PROBLEMS.glob("*.sql"))


def test_every_problem_has_exactly_one_solution() -> None:
    problems = {p.name for p in PROBLEMS}
    solutions = {p.name for p in drill.SOLUTIONS.glob("*.sql")}
    assert problems == solutions
    assert len(problems) == 18


@pytest.mark.parametrize("problem", PROBLEMS, ids=lambda p: p.stem)
def test_reference_passes_and_returns_rows(problem: Path) -> None:
    solution = drill.SOLUTIONS / problem.name
    con = drill.practice_connection()
    assert drill.run(con, solution.read_text()), "a drill whose answer is empty teaches nothing"
    result = drill.check_sql(solution.read_text(), solution, ordered=drill.is_ordered(problem))
    assert result.passed, result.message


@pytest.mark.parametrize("problem", PROBLEMS, ids=lambda p: p.stem)
def test_untouched_starter_does_not_pass(problem: Path) -> None:
    result = drill.check_sql(problem.read_text(), drill.SOLUTIONS / problem.name, ordered=False)
    assert not result.passed


def test_practice_data_is_deterministic() -> None:
    def fingerprint() -> list[drill.Row]:
        con = drill.practice_connection()
        tables = [
            r[0] for r in con.sql("SELECT table_name FROM duckdb_tables() ORDER BY 1").fetchall()
        ]
        return [
            (t, *drill.run(con, f"SELECT COUNT(*), hash(list(t ORDER BY ALL)) FROM {t} AS t")[0])
            for t in tables
        ]

    assert fingerprint() == fingerprint()


# The classic wrong answer for each planted trap must fail.
TRAPS = {
    "01": """SELECT l.line_id, COUNT(*) FROM lines l LEFT JOIN trips t ON t.line_id = l.line_id
             WHERE t.service_date = DATE '2026-11-02' GROUP BY l.line_id""",
    "02": """SELECT stop_id, stop_name FROM stops
             WHERE stop_id NOT IN (SELECT stop_id FROM line_stops)""",
    "05": """WITH p AS (SELECT *, CAST(split_part(scheduled_start, ':', 1) AS INT) * 3600
                + CAST(split_part(scheduled_start, ':', 2) AS INT) * 60 AS s FROM trips)
             SELECT trip_id, line_id, service_date, CAST(service_date + to_seconds(s) AS DATE),
                    CAST(service_date + to_seconds(s) AS TIME)
             FROM p WHERE service_date = DATE '2026-11-02' AND scheduled_start >= '24:00:00'""",
    "08": """WITH latest AS (SELECT trip_id, service_date, ROW_NUMBER() OVER
                (PARTITION BY trip_id ORDER BY posted_at DESC) rn
                FROM cancellations WHERE withdrawn_at IS NULL)
             SELECT t.line_id, l.service_date, COUNT(*) FROM latest l JOIN trips t USING (trip_id)
             WHERE rn = 1 GROUP BY ALL""",
    "16": """SELECT c.trip_id, c.posted_at, MIN(v.observed_at) FROM cancellations c
             JOIN vehicle_positions v ON v.trip_id = c.trip_id AND v.observed_at >= c.posted_at
             GROUP BY ALL""",
}


@pytest.mark.parametrize("key", sorted(TRAPS))
def test_trap_answers_fail(key: str) -> None:
    solution = drill.find(drill.SOLUTIONS, key)
    assert not drill.check_sql(TRAPS[key], solution, ordered=False).passed


def test_compare_ignores_order_unless_asked() -> None:
    rows = [(1, "a"), (2, "b")]
    assert drill.compare(rows, rows[::-1], ordered=False).passed
    assert not drill.compare(rows, rows[::-1], ordered=True).passed


def test_compare_counts_duplicates() -> None:
    assert not drill.compare([(1,), (1,)], [(1,)], ordered=False).passed
    assert not drill.compare([(1,)], [(1,), (1,)], ordered=False).passed


def test_compare_tolerates_rounding_but_not_wrong_values() -> None:
    assert drill.compare([("x", 0.1235)], [("x", 0.124)], ordered=False).passed
    assert not drill.compare([("x", 0.12)], [("x", 0.14)], ordered=False).passed
    assert drill.compare([(Decimal("0.500"),)], [(0.5,)], ordered=False).passed


def test_compare_reports_column_mismatch() -> None:
    result = drill.compare([(1, 2)], [(1,)], ordered=False)
    assert not result.passed
    assert "columns" in result.message


def test_null_is_not_zero() -> None:
    assert not drill.compare([("2", None)], [("2", 0.0)], ordered=False).passed


def test_numbers_compare_across_types() -> None:
    assert drill.compare(
        [("2026-11-02", 3)], [("2026-11-02", Decimal("3.0"))], ordered=False
    ).passed
    assert drill.compare([(3,)], [(3.0,)], ordered=True).passed
    assert not drill.compare([(True,)], [(1,)], ordered=False).passed


def test_list_values_do_not_crash() -> None:
    assert drill.compare([(["a", "b"],)], [(["a", "b"],)], ordered=False).passed
    assert not drill.compare([(["a"],)], [({"x": 1},)], ordered=False).passed


def test_pairing_finds_a_valid_match() -> None:
    expected = [("x", 1.000), ("x", 1.0015)]
    actual = [("x", 1.0008), ("x", 0.9995)]
    assert drill.compare(expected, actual, ordered=False).passed


def test_ordered_row_count_mismatch() -> None:
    assert not drill.compare([(1,), (2,)], [(1,)], ordered=True).passed


def test_failing_or_rowless_attempts_are_reported_not_raised() -> None:
    solution = drill.find(drill.SOLUTIONS, "1")
    assert "failed" in drill.check_sql("SELECT nope FROM lines", solution, ordered=False).message
    assert not drill.check_sql("CREATE TABLE x (a INT)", solution, ordered=False).passed
    ok = drill.check_sql(
        "CREATE TABLE x AS SELECT 1; " + solution.read_text(), solution, ordered=False
    )
    assert ok.passed


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(drill, "ROOT", tmp_path)
    monkeypatch.setattr(drill, "ATTEMPTS", tmp_path / "attempts")
    monkeypatch.setattr(drill, "STATE", tmp_path / "attempts" / ".state.json")
    monkeypatch.setattr(drill, "LOG", tmp_path / "sql-log.md")
    monkeypatch.setattr(drill, "PROBLEMS", drill.PROBLEMS)
    monkeypatch.setattr(drill, "SOLUTIONS", drill.SOLUTIONS)
    return tmp_path


def _relative_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    # Problem paths live outside the sandbox ROOT; print them as they are.
    monkeypatch.setattr(Path, "relative_to", lambda self, *_: self)


def test_start_check_log_and_restart(sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _relative_safe(monkeypatch)
    attempt = sandbox / "attempts" / "01-trips-per-line.sql"
    solution = drill.find(drill.SOLUTIONS, "01").read_text()

    assert drill.main(["start", "1"]) == 0
    assert drill.main(["check", "01"]) == 1  # untouched starter
    attempt.write_text(solution)
    assert drill.main(["check", "001"]) == 0
    assert drill.main(["check", "01"]) == 0  # second pass: not logged again
    log = (sandbox / "sql-log.md").read_text()
    assert log.count("01-trips-per-line") == 1
    assert "| 2 |" in log  # passed on the second check

    # Restarting resets the attempt, so the old answer can't log a fake time.
    assert drill.main(["start", "01"]) == 0
    assert attempt.read_text() == drill.find(drill.PROBLEMS, "01").read_text()
    assert list((sandbox / "attempts").glob("01-trips-per-line.*.bak"))
    assert drill.main(["check", "01"]) == 1
    state = drill.load_state()["01-trips-per-line"]
    assert state["ever_passed"]
    assert not state["passed"]
    assert (sandbox / "sql-log.md").read_text().count("01-trips-per-line") == 1


def test_check_before_start_exits(sandbox: Path) -> None:
    with pytest.raises(SystemExit):
        drill.main(["check", "02"])
