"""Pure rules of publish: type mapping, DDL, and the row-count guard (pipeline spec section 13)."""

import pytest
from ghostbus_publish.engine import ServingTable, create_table_sql, pg_type, row_count_problem
from hypothesis import given
from hypothesis import strategies as st


@pytest.mark.parametrize(
    ("duck", "pg"),
    [
        ("VARCHAR", "text"),
        ("INTEGER", "integer"),
        ("BIGINT", "bigint"),
        ("DOUBLE", "double precision"),
        ("BOOLEAN", "boolean"),
        ("DATE", "date"),
        ("TIMESTAMP WITH TIME ZONE", "timestamptz"),
    ],
)
def test_maps_every_type_the_gold_tables_use(duck: str, pg: str) -> None:
    assert pg_type(duck) == pg


@pytest.mark.parametrize("duck", ["HUGEINT", "VARCHAR[]", "STRUCT(a INTEGER)", "TIMESTAMP"])
def test_refuses_types_it_has_not_been_taught(duck: str) -> None:
    # A new type in a gold table must be a deliberate change here, not a silent text column.
    with pytest.raises(ValueError, match="no Postgres type"):
        pg_type(duck)


def test_ddl_quotes_every_name() -> None:
    table = ServingTable("reliability", "select 1", key=("line", "time_window"))
    columns = [("line", "VARCHAR"), ("time_window", "VARCHAR"), ('odd"name', "BIGINT")]
    assert create_table_sql(table, columns).as_string() == (
        'CREATE TABLE serving."reliability__new" ('
        '"line" text, "time_window" text, "odd""name" bigint)'
    )


@pytest.mark.parametrize(
    "name", ["Reliability", "reliability__new", "x__old", "1line", "a" * 50, "has space"]
)
def test_refuses_table_names_ops_or_postgres_would_reject(name: str) -> None:
    with pytest.raises(ValueError, match="bad serving table name"):
        ServingTable(name, "select 1", key=("id",))


def test_a_forced_empty_load_is_not_a_baseline() -> None:
    # After a forced load of 0 rows, any later non-empty load would be "infinitely" different.
    assert row_count_problem(0, 25_000, force=False) is None


@given(st.integers(1, 10**7), st.floats(0.8, 1.2))
def test_a_load_within_20_percent_passes(previous: int, ratio: float) -> None:
    new = round(previous * ratio)
    if abs(new - previous) <= 0.2 * previous and new > 0:
        assert row_count_problem(previous, new, force=False) is None


@given(st.integers(10, 10**7), st.sampled_from([0.5, 0.79, 1.21, 3.0]))
def test_a_load_outside_20_percent_is_refused_unless_forced(previous: int, ratio: float) -> None:
    new = max(1, round(previous * ratio))
    if abs(new - previous) > 0.2 * previous:
        problem = row_count_problem(previous, new, force=False)
        assert problem is not None
        assert str(previous) in problem
        assert row_count_problem(previous, new, force=True) is None


def test_the_first_load_has_nothing_to_compare_with() -> None:
    assert row_count_problem(None, 5, force=False) is None


@pytest.mark.parametrize("previous", [None, 10])
def test_an_empty_load_is_refused_unless_forced(previous: int | None) -> None:
    assert row_count_problem(previous, 0, force=False) == "no rows"
    assert row_count_problem(previous, 0, force=True) is None


def test_the_recent_windows_match_their_constants() -> None:
    from ghostbus_publish.tables import FEED_HEALTH_DAYS, RECENT_OUTCOME_DAYS, TABLES

    by_name = {t.name: t.source_sql for t in TABLES}
    assert f"- {RECENT_OUTCOME_DAYS}" in by_name["trip_outcome_recent"]
    assert f"INTERVAL {FEED_HEALTH_DAYS} DAY" in by_name["feed_health"]


def test_a_table_without_a_limit_may_double() -> None:
    # A new schedule ZIP doubles the line tables; a young trend gains 50% a week.
    assert row_count_problem(15_000, 30_000, force=False, max_change=None) is None
    assert row_count_problem(15_000, 0, force=False, max_change=None) == "no rows"


def test_only_grow_in_steps_tables_skip_the_guard() -> None:
    from ghostbus_publish.tables import TABLES

    unguarded = {t.name for t in TABLES if t.max_change is None}
    assert unguarded == {
        "schedule_version", "line", "line_direction", "line_stop", "line_trend", "method_param",
        "cancellation_current", "cancellation_as_of",
    }  # fmt: skip


def test_an_empty_load_is_allowed_only_where_empty_is_normal() -> None:
    from ghostbus_publish.tables import TABLES

    assert row_count_problem(5, 0, force=False, max_change=None, allow_empty=True) is None
    assert {t.name for t in TABLES if t.allow_empty} == {"cancellation_current"}


def test_only_open_date_tables_are_left_out_of_a_plain_publish() -> None:
    from ghostbus_publish.tables import TABLES

    assert {t.name for t in TABLES if not t.default} == {
        "cancellation_current",
        "cancellation_as_of",
    }
