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


def test_ddl_quotes_names_and_suffixes_constraints() -> None:
    table = ServingTable("reliability", "select 1", key=("line", "time_window"))
    sql = create_table_sql(
        table, [("line", "VARCHAR"), ("time_window", "VARCHAR"), ("n", "BIGINT")]
    )
    assert sql == (
        'CREATE TABLE serving."reliability__new" ("line" text, "time_window" text, "n" bigint)'
    )


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
