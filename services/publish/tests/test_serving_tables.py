"""Every serving table publishes from a real dbt build (the test world), and republishing the
same build changes nothing (hard rule 2)."""

from pathlib import Path
from typing import Any

import duckdb
import pytest
from dbt_world import build_world, run_dbt
from ghostbus_api.migrations import downgrade_to_base, upgrade_to_head
from ghostbus_publish.engine import publish
from ghostbus_publish.tables import TABLES
from sqlalchemy import Engine, create_engine, text

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def warehouse(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp = tmp_path_factory.mktemp("serving")
    return run_dbt(build_world(tmp), tmp)


@pytest.fixture
def pg(database_url: str) -> Any:
    engine = create_engine(database_url)
    with engine.begin() as con:
        con.execute(text("DROP SCHEMA IF EXISTS serving, ops CASCADE"))
        con.execute(text("DROP TABLE IF EXISTS public.alembic_version"))
    upgrade_to_head(database_url)
    yield engine
    downgrade_to_base(database_url)
    engine.dispose()


def content(pg: Engine, table: str) -> tuple[int, str]:
    with pg.connect() as con:
        # Table names come from TABLES (code), never from input.
        query = (
            "SELECT count(*), md5(coalesce(string_agg(t::text, '|' ORDER BY t::text), '')) "
            f"FROM serving.{table} AS t"
        )
        n, digest = con.execute(text(query)).one()
    return n, digest


def test_every_serving_table_publishes_and_matches_its_source(
    pg: Engine, database_url: str, warehouse: Path
) -> None:
    results = publish(warehouse, database_url, TABLES, source="test world")
    published = {r.table: r.row_count for r in results}
    assert set(published) == {t.name for t in TABLES}
    with duckdb.connect(str(warehouse), read_only=True) as duck:
        for table in TABLES:
            (expected,) = duck.execute(f"SELECT count(*) FROM ({table.source_sql})").fetchall()[0]
            assert published[table.name] == expected, table.name
            assert content(pg, table.name)[0] == expected, table.name
    with pg.connect() as con:
        rows = con.execute(text(
            "SELECT count(*), count(DISTINCT run_id) FROM ops.publish_run"
            " WHERE status = 'succeeded'"
        )).one()  # fmt: skip
    assert tuple(rows) == (len(TABLES), 1)


def test_republishing_the_same_build_changes_nothing(
    pg: Engine, database_url: str, warehouse: Path
) -> None:
    publish(warehouse, database_url, TABLES, source="test world")
    before = {t.name: content(pg, t.name) for t in TABLES}
    publish(warehouse, database_url, TABLES, source="test world")
    assert {t.name: content(pg, t.name) for t in TABLES} == before
