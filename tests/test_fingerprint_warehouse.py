"""The drill's fingerprint ignores row order but sees any changed value."""

import importlib.util
from pathlib import Path

import duckdb

spec = importlib.util.spec_from_file_location(
    "fingerprint_warehouse", Path(__file__).parents[1] / "scripts" / "fingerprint_warehouse.py"
)
assert spec
assert spec.loader
fw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fw)


def _fp(rows: list[tuple[int, str | None]]) -> dict[str, list[object]]:
    con = duckdb.connect()
    con.execute("CREATE TABLE t (a INTEGER, b VARCHAR)")
    if rows:
        con.executemany("INSERT INTO t VALUES (?, ?)", rows)
    return fw.fingerprints(con)


def test_row_order_does_not_matter() -> None:
    assert _fp([(1, "x"), (2, None)]) == _fp([(2, None), (1, "x")])


def test_a_changed_value_or_extra_row_changes_it() -> None:
    base = _fp([(1, "x"), (2, None)])
    assert _fp([(1, "x"), (2, "y")]) != base
    assert _fp([(1, "x"), (2, None), (2, None)]) != base


def test_an_empty_table_has_a_stable_fingerprint() -> None:
    assert _fp([]) == {"main.t": [0, "empty"]}
