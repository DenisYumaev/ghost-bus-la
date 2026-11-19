"""publish against a real Postgres 16 (compose.test.yml): load, validate, swap (ADR-007)."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import duckdb
import pytest
from ghostbus_api.migrations import downgrade_to_base, upgrade_to_head
from ghostbus_publish.engine import PublishError, ServingTable, publish
from sqlalchemy import Engine, create_engine, text

pytestmark = pytest.mark.integration

WIDGET = ServingTable("widget", "select * from widgets", key=("id",), indexes=(("color",),))


@pytest.fixture
def pg(database_url: str) -> Iterator[Engine]:
    engine = create_engine(database_url)
    with engine.begin() as con:
        con.execute(text("DROP SCHEMA IF EXISTS serving, ops CASCADE"))
        con.execute(text("DROP TABLE IF EXISTS public.alembic_version"))
    upgrade_to_head(database_url)
    yield engine
    downgrade_to_base(database_url)
    engine.dispose()


def warehouse(tmp_path: Path, n: int, *, null_key: bool = False) -> Path:
    path = tmp_path / f"w{n}{null_key}.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute(f"""
            CREATE OR REPLACE TABLE widgets AS
            SELECT CASE WHEN {null_key} AND i = 0 THEN NULL ELSE i END::INTEGER AS id,
                   'c' || (i % 3) AS color, i * CAST(1.5 AS DOUBLE) AS weight, i % 2 = 0 AS even,
                   DATE '2026-11-15' + CAST(i AS INTEGER) AS day,
                   TIMESTAMPTZ '2026-11-15 16:00:00+00' AS at,
                   CASE WHEN i = 1 THEN NULL ELSE i::BIGINT END AS maybe
            FROM range({n}) AS t(i)""")  # noqa: S608
    return path


def rows(pg: Engine, sql: str) -> list[tuple[Any, ...]]:
    with pg.connect() as con:
        return [tuple(r) for r in con.execute(text(sql))]


def test_first_publish_creates_the_table_with_types_key_and_index(
    pg: Engine, database_url: str, tmp_path: Path
) -> None:
    results = publish(warehouse(tmp_path, 10), database_url, [WIDGET], source="test")
    assert [(r.table, r.row_count) for r in results] == [("widget", 10)]
    assert rows(pg, "SELECT count(*), count(maybe), sum(id) FROM serving.widget") == [(10, 9, 45)]
    types = dict(rows(pg, "SELECT column_name, data_type FROM information_schema.columns "
                          "WHERE table_schema = 'serving' AND table_name = 'widget'"))  # fmt: skip
    assert types == {
        "id": "integer", "color": "text", "weight": "double precision", "even": "boolean",
        "day": "date", "at": "timestamp with time zone", "maybe": "bigint",
    }  # fmt: skip
    keys = rows(pg, "SELECT indexdef FROM pg_indexes WHERE schemaname = 'serving'")
    assert any("UNIQUE" in k and "(id)" in k for (k,) in keys)
    assert any("(color)" in k for (k,) in keys)
    assert rows(pg, "SELECT table_name, status, row_count, source FROM ops.publish_run") == [
        ("widget", "succeeded", 10, "test")
    ]


def test_republishing_swaps_cleanly_every_time(
    pg: Engine, database_url: str, tmp_path: Path
) -> None:
    for n in (10, 11, 12):  # within 20% of the previous load each time
        publish(warehouse(tmp_path, n), database_url, [WIDGET], source="test")
    assert rows(pg, "SELECT count(*) FROM serving.widget") == [(12,)]
    tables = rows(pg, "SELECT tablename FROM pg_tables WHERE schemaname = 'serving'")
    assert tables == [("widget",)]  # no __new or __old left behind
    assert rows(pg, "SELECT count(*) FROM ops.publish_run WHERE status = 'succeeded'") == [(3,)]


def test_a_load_far_from_the_last_is_refused_and_the_live_table_stays(
    pg: Engine, database_url: str, tmp_path: Path
) -> None:
    publish(warehouse(tmp_path, 10), database_url, [WIDGET], source="test")
    with pytest.raises(PublishError, match="widget"):
        publish(warehouse(tmp_path, 3), database_url, [WIDGET], source="test")
    assert rows(pg, "SELECT count(*) FROM serving.widget") == [(10,)]
    assert rows(pg, "SELECT tablename FROM pg_tables WHERE schemaname = 'serving'") == [("widget",)]
    failed = rows(pg, "SELECT row_count, error FROM ops.publish_run WHERE status = 'failed'")
    assert len(failed) == 1
    assert "10" in str(failed[0][1])
    publish(warehouse(tmp_path, 3), database_url, [WIDGET], source="test", force=True)
    assert rows(pg, "SELECT count(*) FROM serving.widget") == [(3,)]


def test_null_keys_are_refused(pg: Engine, database_url: str, tmp_path: Path) -> None:
    publish(warehouse(tmp_path, 10), database_url, [WIDGET], source="test")
    with pytest.raises(PublishError, match="NULL"):
        publish(warehouse(tmp_path, 10, null_key=True), database_url, [WIDGET], source="test")
    assert rows(pg, "SELECT count(*), min(id) FROM serving.widget") == [(10, 0)]


def test_a_leftover_staging_table_from_a_crash_is_replaced(
    pg: Engine, database_url: str, tmp_path: Path
) -> None:
    with pg.begin() as con:
        con.execute(text("CREATE TABLE serving.widget__new (junk text)"))
    publish(warehouse(tmp_path, 4), database_url, [WIDGET], source="test")
    assert rows(pg, "SELECT count(*) FROM serving.widget") == [(4,)]


def test_a_failure_inside_the_swap_rolls_everything_back(
    pg: Engine, database_url: str, tmp_path: Path
) -> None:
    # ops.publish_run refuses an upper-case table name, and its row is written inside the swap
    # transaction: the renames must roll back with it, leaving the live table as it was.
    table = ServingTable("Widget", "select * from widgets", key=("id",))
    with pg.begin() as con:
        con.execute(text('CREATE TABLE serving."Widget" AS SELECT 1 AS id'))
    with pytest.raises(PublishError):
        publish(warehouse(tmp_path, 5), database_url, [table], source="test")
    assert rows(pg, 'SELECT count(*) FROM serving."Widget"') == [(1,)]
    assert rows(pg, "SELECT count(*) FROM pg_tables WHERE schemaname = 'serving'") == [(1,)]


def test_one_failing_table_does_not_stop_the_others(
    pg: Engine, database_url: str, tmp_path: Path
) -> None:
    broken = ServingTable("broken", "select * from no_such_table", key=("id",))
    with pytest.raises(PublishError, match="broken"):
        publish(warehouse(tmp_path, 4), database_url, [broken, WIDGET], source="test")
    assert rows(pg, "SELECT count(*) FROM serving.widget") == [(4,)]
    assert rows(pg, "SELECT table_name, status FROM ops.publish_run ORDER BY table_name") == [
        ("broken", "failed"), ("widget", "succeeded"),
    ]  # fmt: skip
