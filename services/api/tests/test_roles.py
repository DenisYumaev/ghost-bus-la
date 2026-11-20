"""Least-privilege roles (ADR-007 decision 5): publish runs as `pipeline`, the API reads as
`api`, and neither can do the other's job. Run against real Postgres 16."""

import secrets
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from dbt_world import build_world, run_dbt
from ghostbus_api import roles
from ghostbus_api.migrations import _config, downgrade_to_base, upgrade_to_head
from ghostbus_api.roles import passwords_from, set_passwords
from ghostbus_publish.engine import publish
from ghostbus_publish.tables import TABLES
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError

pytestmark = pytest.mark.integration

PERMISSION_DENIED = "42501"  # SQLSTATE for "permission denied" and "must be owner"
PASSWORDS = {"pipeline": secrets.token_urlsafe(24) + ":@/%", "api": secrets.token_urlsafe(24)}


def as_role(database_url: str, role: str) -> str:
    return (
        make_url(database_url)
        .set(username=role, password=PASSWORDS[role])
        .render_as_string(hide_password=False)
    )


@pytest.fixture(scope="module")
def warehouse(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp = tmp_path_factory.mktemp("roles")
    return run_dbt(build_world(tmp), tmp)


@pytest.fixture
def migrated(empty_db: Engine, database_url: str) -> Iterator[str]:
    upgrade_to_head(database_url)
    set_passwords(database_url, PASSWORDS)
    yield database_url
    downgrade_to_base(database_url)


def test_publish_as_pipeline_and_read_as_api(migrated: str, warehouse: Path) -> None:
    publish(warehouse, as_role(migrated, "pipeline"), TABLES, source="test world")
    api = create_engine(as_role(migrated, "api"))
    try:
        with api.connect() as con:
            # Every table publish created is readable through the default privileges, swap or not.
            for table in TABLES:
                con.execute(text(f"SELECT count(*) FROM serving.{table.name}"))
            assert con.execute(text("SELECT count(*) FROM ops.publish_run")).scalar_one() > 0
    finally:
        api.dispose()
    # A second publish swaps every table: the api role must still read the new objects.
    publish(warehouse, as_role(migrated, "pipeline"), TABLES, source="test world", force=True)
    api = create_engine(as_role(migrated, "api"))
    try:
        with api.connect() as con:
            con.execute(text("SELECT count(*) FROM serving.line"))
    finally:
        api.dispose()


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO ops.publish_run (run_id, table_name, status, row_count, source, started_at)"
        " VALUES (gen_random_uuid(), 'x', 'succeeded', 1, 'x', now())",
        "CREATE TABLE serving.sneaky (id int)",
        "DROP TABLE serving.line",
        "DELETE FROM serving.line",
        "TRUNCATE serving.line",
        "UPDATE ops.feed_status SET updated_by = 'pipeline'",
        "TRUNCATE ops.publish_run",
        # PostgreSQL 15+ already denies this by default; the migration's REVOKE keeps it so.
        "CREATE TABLE public.sneaky (id int)",
    ],
)
def test_api_role_can_only_read(migrated: str, warehouse: Path, statement: str) -> None:
    publish(warehouse, as_role(migrated, "pipeline"), TABLES, source="test world")
    api = create_engine(as_role(migrated, "api"))
    try:
        with pytest.raises(ProgrammingError) as denied, api.begin() as con:
            con.execute(text(statement))
        # The SQLSTATE, not the message: a typo or a missing table would fail differently.
        assert denied.value.orig.sqlstate == PERMISSION_DENIED  # type: ignore[union-attr]
    finally:
        api.dispose()


@pytest.mark.parametrize(
    "statement",
    ["DELETE FROM ops.publish_run", "UPDATE ops.publish_run SET row_count = 0",
     "TRUNCATE ops.publish_run", "DELETE FROM ops.deploy", "SELECT * FROM ops.consumer_cursor",
     "CREATE TABLE ops.sneaky (id int)", "CREATE TABLE public.sneaky (id int)"],
)  # fmt: skip
def test_pipeline_role_cannot_touch_the_rest(migrated: str, statement: str) -> None:
    pipeline = create_engine(as_role(migrated, "pipeline"))
    try:
        with pytest.raises(ProgrammingError) as denied, pipeline.begin() as con:
            con.execute(text(statement))
        assert denied.value.orig.sqlstate == PERMISSION_DENIED  # type: ignore[union-attr]
    finally:
        pipeline.dispose()


def test_setting_passwords_again_changes_nothing(migrated: str) -> None:
    set_passwords(migrated, PASSWORDS)
    engine = create_engine(as_role(migrated, "api"))
    try:
        with engine.connect() as con:
            assert con.execute(text("SELECT current_user")).scalar_one() == "api"
    finally:
        engine.dispose()


def test_short_or_missing_passwords_are_refused() -> None:
    with pytest.raises(ValueError, match="GHOSTBUS_API_DB_PASSWORD"):
        passwords_from(
            {"GHOSTBUS_PIPELINE_DB_PASSWORD": "x" * 30, "GHOSTBUS_API_DB_PASSWORD": "short"}
        )
    assert passwords_from(
        {"GHOSTBUS_PIPELINE_DB_PASSWORD": "p" * 24, "GHOSTBUS_API_DB_PASSWORD": "a" * 24}
    ) == {"pipeline": "p" * 24, "api": "a" * 24}


def test_pipeline_can_upsert_feed_status(migrated: str) -> None:
    pipeline = create_engine(as_role(migrated, "pipeline"))
    try:
        with pipeline.begin() as con:
            for _ in range(2):  # insert, then update the same row
                con.execute(text(
                    "INSERT INTO ops.feed_status (feed, last_success_at, updated_by)"
                    " VALUES ('trip_updates', now(), 'pipeline') ON CONFLICT (feed)"
                    " DO UPDATE SET last_success_at = excluded.last_success_at"
                ))  # fmt: skip
    finally:
        pipeline.dispose()


def test_an_existing_role_is_stripped_of_extra_powers(empty_db: Engine, database_url: str) -> None:
    with empty_db.begin() as con:
        con.execute(text("DROP ROLE IF EXISTS api"))
        con.execute(text("CREATE ROLE api NOLOGIN CREATEDB CREATEROLE"))
    upgrade_to_head(database_url)
    try:
        with empty_db.connect() as con:
            row = con.execute(text(
                "SELECT rolcreatedb, rolcreaterole, rolsuper FROM pg_roles WHERE rolname = 'api'"
            )).one()  # fmt: skip
        assert tuple(row) == (False, False, False)
    finally:
        downgrade_to_base(database_url)


def test_serving_tables_made_before_the_roles_pass_to_pipeline(
    empty_db: Engine, database_url: str, warehouse: Path
) -> None:
    # A database published by the owner before 0002 existed: pipeline must be able to swap.
    command.upgrade(_config(database_url), "0001")
    publish(warehouse, database_url, TABLES, source="as owner")
    upgrade_to_head(database_url)
    try:
        set_passwords(database_url, PASSWORDS)
        publish(warehouse, as_role(database_url, "pipeline"), TABLES, source="test", force=True)
        with empty_db.connect() as con:
            owners = con.execute(text(
                "SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname = 'serving'"
            )).scalars().all()  # fmt: skip
        assert owners == ["pipeline"]
    finally:
        downgrade_to_base(database_url)


def test_upgrade_downgrade_upgrade(empty_db: Engine, database_url: str) -> None:
    upgrade_to_head(database_url)
    downgrade_to_base(database_url)
    upgrade_to_head(database_url)
    downgrade_to_base(database_url)
    with empty_db.connect() as con:
        left = con.execute(text(
            "SELECT count(*) FROM pg_roles WHERE rolname IN ('pipeline', 'api')"
        )).scalar_one()  # fmt: skip
    assert left == 0


def test_the_password_never_reaches_the_server_in_plain_text(migrated: str) -> None:
    with create_engine(migrated).connect() as con:
        stored = con.execute(
            text("SELECT rolpassword FROM pg_authid WHERE rolname = 'api'")
        ).scalar_one()
    assert stored.startswith("SCRAM-SHA-256$")
    assert PASSWORDS["api"] not in stored


def test_errors_withhold_details(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], database_url: str
) -> None:
    # A wrong owner password: the connection fails, and libpq's message could quote details.
    wrong = make_url(database_url).set(password="wrong-password")  # noqa: S106 - deliberately wrong
    url = wrong.render_as_string(hide_password=False)
    monkeypatch.setenv("GHOSTBUS_DATABASE_URL", url)
    monkeypatch.setenv("GHOSTBUS_PIPELINE_DB_PASSWORD", "p" * 30)
    monkeypatch.setenv("GHOSTBUS_API_DB_PASSWORD", "a" * 30)
    assert roles.main() == 1
    err = capsys.readouterr().err
    assert "details withheld" in err
    assert "wrong-password" not in err
