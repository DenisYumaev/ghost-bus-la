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
    result: dict[str, list[object]] = fw.fingerprints(con)
    return result


def test_row_order_does_not_matter() -> None:
    assert _fp([(1, "x"), (2, None)]) == _fp([(2, None), (1, "x")])


def test_a_changed_value_or_extra_row_changes_it() -> None:
    base = _fp([(1, "x"), (2, None)])
    assert _fp([(1, "x"), (2, "y")]) != base
    assert _fp([(1, "x"), (2, None), (2, None)]) != base


def test_an_empty_table_has_a_stable_fingerprint() -> None:
    fp = _fp([])
    assert fp["main.t"][:2] == [0, "empty"]
    assert fp == _fp([])


def test_null_and_the_string_null_differ() -> None:
    assert _fp([(1, None)]) != _fp([(1, "NULL")])


def test_views_are_fingerprinted_like_tables() -> None:
    con = duckdb.connect()
    con.execute("CREATE TABLE t AS SELECT * FROM (VALUES (1, 'x')) AS v(a, b)")
    con.execute("CREATE VIEW v AS SELECT a, b FROM t")
    fp = fw.fingerprints(con)
    assert fp["main.v"] == fp["main.t"]


def test_only_the_open_database_is_fingerprinted() -> None:
    con = duckdb.connect()
    con.execute("CREATE TABLE t (a INTEGER)")
    con.execute("ATTACH ':memory:' AS other")
    con.execute("CREATE TABLE other.main.t (a INTEGER)")
    con.execute("INSERT INTO other.main.t VALUES (1)")
    assert list(fw.fingerprints(con)) == ["main.t"]


def test_a_column_type_change_counts() -> None:
    a = duckdb.connect()
    a.execute("CREATE TABLE t AS SELECT 1::INTEGER AS a")
    b = duckdb.connect()
    b.execute("CREATE TABLE t AS SELECT 1::BIGINT AS a")
    assert fw.fingerprints(a) != fw.fingerprints(b)


def test_timestamptz_is_the_same_in_any_session_time_zone() -> None:
    fps = []
    for tz in ("UTC", "America/Los_Angeles"):
        con = duckdb.connect()
        con.execute(f"SET TimeZone = '{tz}'")
        con.execute("CREATE TABLE t AS SELECT TIMESTAMPTZ '2026-11-15 16:00:00+00' AS at")
        fps.append(fw.fingerprints(con))
    assert fps[0] == fps[1]


def test_a_column_named_like_the_row_alias_is_still_hashed_by_row() -> None:
    con = duckdb.connect()
    con.execute("CREATE TABLE x AS SELECT * FROM (VALUES (1, 10)) AS v(t, v)")
    other = duckdb.connect()
    other.execute("CREATE TABLE x AS SELECT * FROM (VALUES (1, 20)) AS v(t, v)")
    assert fw.fingerprints(con) != fw.fingerprints(other)


def test_nested_values_and_quoted_names() -> None:
    con = duckdb.connect()
    con.execute("""CREATE TABLE "we""ird" AS SELECT [1, 2] AS l, {'k': 'v'} AS s""")
    other = duckdb.connect()
    other.execute("""CREATE TABLE "we""ird" AS SELECT [1, 3] AS l, {'k': 'v'} AS s""")
    assert fw.fingerprints(con) != fw.fingerprints(other)
