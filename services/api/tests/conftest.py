"""Integration fixtures: a real Postgres 16 from compose.test.yml (API spec section 9).

Set GHOSTBUS_TEST_DATABASE_URL (make test-integration does) to run them; without it they are
skipped, so `make test` stays offline and needs no Docker.
"""

import os
from collections.abc import Iterator

import pytest
from ghostbus_api.migrations import downgrade_to_base
from sqlalchemy import Engine, create_engine, text


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("GHOSTBUS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("GHOSTBUS_TEST_DATABASE_URL not set (run make test-integration)")
    return url


@pytest.fixture
def empty_db(database_url: str) -> Iterator[Engine]:
    """A database with no project schemas: every test starts from nothing."""
    engine = create_engine(database_url)
    with engine.begin() as con:
        con.execute(text("DROP SCHEMA IF EXISTS serving, ops CASCADE"))
        con.execute(text("DROP TABLE IF EXISTS public.alembic_version"))
    yield engine
    downgrade_to_base(database_url)
    engine.dispose()


@pytest.fixture(scope="module")
def url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """A Postgres with the migrations applied and the dbt test world published into serving,
    shared by each endpoint test module."""
    from dbt_world import build_world, run_dbt
    from ghostbus_api.migrations import upgrade_to_head
    from ghostbus_publish.engine import publish
    from ghostbus_publish.tables import TABLES

    url = os.environ.get("GHOSTBUS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("GHOSTBUS_TEST_DATABASE_URL not set (run make test-integration)")
    engine = create_engine(url)
    with engine.begin() as con:
        con.execute(text("DROP SCHEMA IF EXISTS serving, ops CASCADE"))
        con.execute(text("DROP TABLE IF EXISTS public.alembic_version"))
    engine.dispose()
    upgrade_to_head(url)
    tmp = tmp_path_factory.mktemp("api")
    publish(run_dbt(build_world(tmp), tmp), url, TABLES, source="test world")
    yield url
    downgrade_to_base(url)
