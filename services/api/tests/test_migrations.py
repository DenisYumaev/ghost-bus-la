"""Migrations: apply to an empty database, re-run safely, and roll back (API spec section 9)."""

import uuid
from datetime import UTC, datetime

import pytest
from ghostbus_api.migrations import downgrade_to_base, upgrade_to_head
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration


def _schemas(engine: Engine) -> set[str]:
    return set(inspect(engine).get_schema_names())


def test_upgrade_creates_the_serving_and_ops_schemas(empty_db: Engine, database_url: str) -> None:
    upgrade_to_head(database_url)
    assert {"serving", "ops"} <= _schemas(empty_db)
    ops = set(inspect(empty_db).get_table_names(schema="ops"))
    assert ops == {"publish_run", "consumer_cursor", "feed_status", "deploy"}
    # ADR-007: serving tables belong to publish; the migration creates only the schema.
    assert inspect(empty_db).get_table_names(schema="serving") == []


def test_upgrade_twice_is_a_no_op(empty_db: Engine, database_url: str) -> None:
    upgrade_to_head(database_url)
    upgrade_to_head(database_url)
    with empty_db.connect() as con:
        assert con.execute(text("SELECT count(*) FROM alembic_version")).scalar_one() == 1


def test_downgrade_removes_everything_and_upgrade_works_again(
    empty_db: Engine, database_url: str
) -> None:
    upgrade_to_head(database_url)
    downgrade_to_base(database_url)
    assert not {"serving", "ops"} & _schemas(empty_db)
    upgrade_to_head(database_url)
    assert {"serving", "ops"} <= _schemas(empty_db)


def _publish_run(**overrides: object) -> dict[str, object]:
    now = datetime(2026, 11, 17, 19, 0, tzinfo=UTC)
    row: dict[str, object] = {
        "run_id": uuid.uuid4(), "table_name": "reliability", "status": "succeeded",
        "row_count": 10, "source": "service dates 2026-11-15..2026-11-15",
        "started_at": now, "finished_at": now, "error": None,
    }  # fmt: skip
    row.update(overrides)
    return row


INSERT_RUN = text(
    "INSERT INTO ops.publish_run (run_id, table_name, status, row_count, source, started_at,"
    " finished_at, error) VALUES (:run_id, :table_name, :status, :row_count, :source,"
    " :started_at, :finished_at, :error)"
)


@pytest.mark.parametrize(
    "bad",
    [
        {"status": "done", "error": "x"},  # not an allowed status (and nothing else wrong)
        {"row_count": -1},
        {"status": "succeeded", "row_count": None},  # a success must say how many rows
        {"status": "succeeded", "error": "boom"},  # a success has no error
        {"status": "failed", "error": None},  # a failure must say why
        {"finished_at": datetime(2026, 11, 17, 18, 0, tzinfo=UTC)},  # finished before it started
        {"status": "failed", "row_count": None, "error": "  "},  # a failure must say why
        {"source": ""},
        {"table_name": "Reliability"},  # the API looks tables up by exact lowercase name
        {"table_name": "reliability "},
        {"table_name": "reliability__new"},  # record the live name, not the staging table
    ],
)
def test_publish_run_rejects_inconsistent_rows(
    empty_db: Engine, database_url: str, bad: dict[str, object]
) -> None:
    upgrade_to_head(database_url)
    with pytest.raises(IntegrityError), empty_db.begin() as con:
        con.execute(INSERT_RUN, _publish_run(**bad))


def test_publish_run_accepts_a_success_and_a_failure(empty_db: Engine, database_url: str) -> None:
    upgrade_to_head(database_url)
    with empty_db.begin() as con:
        con.execute(INSERT_RUN, _publish_run())
        con.execute(INSERT_RUN, _publish_run(status="failed", row_count=None, error="row count"))
        assert con.execute(text("SELECT count(*) FROM ops.publish_run")).scalar_one() == 2


@pytest.mark.parametrize(
    ("sql", "params"),
    [
        # Only the detector and the pipeline write feed status, never ingest (API spec section 7).
        (
            "INSERT INTO ops.feed_status (feed, last_success_at, updated_by)"
            " VALUES ('trip_updates', now(), 'ingest')",
            {},
        ),
        (
            "INSERT INTO ops.feed_status (feed, last_success_at, updated_by)"
            " VALUES ('buses', now(), 'pipeline')",
            {},
        ),
        ("INSERT INTO ops.deploy (git_sha, outcome) VALUES (:sha, 'maybe')", {"sha": "a" * 40}),
        *[
            ("INSERT INTO ops.deploy (git_sha, outcome) VALUES (:sha, 'succeeded')", {"sha": sha})
            for sha in ("abc123", "a" * 39, "a" * 41, "A" * 40, "a" * 40 + "\n")
        ],
        (
            "INSERT INTO ops.deploy (git_sha, previous_sha, outcome)"
            " VALUES (:sha, 'abc', 'failed')",
            {"sha": "a" * 40},
        ),
        ("INSERT INTO ops.consumer_cursor (consumer, position) VALUES ('detector', '')", {}),
    ],
)
def test_ops_tables_reject_values_outside_their_domain(
    empty_db: Engine, database_url: str, sql: str, params: dict[str, str]
) -> None:
    upgrade_to_head(database_url)
    with pytest.raises(IntegrityError), empty_db.begin() as con:
        con.execute(text(sql), params)


def test_consumer_cursor_is_one_row_per_consumer(empty_db: Engine, database_url: str) -> None:
    upgrade_to_head(database_url)
    upsert = text(
        "INSERT INTO ops.consumer_cursor (consumer, position) VALUES ('detector', :p)"
        " ON CONFLICT (consumer) DO UPDATE SET position = excluded.position, updated_at = now()"
    )
    with empty_db.begin() as con:
        con.execute(upsert, {"p": "a.pb"})
        con.execute(upsert, {"p": "b.pb"})
        rows = con.execute(text("SELECT consumer, position FROM ops.consumer_cursor")).all()
    assert [tuple(r) for r in rows] == [("detector", "b.pb")]


@pytest.mark.parametrize(
    ("sql", "params"),
    [
        *[
            (
                "INSERT INTO ops.feed_status (feed, last_success_at, updated_by)"
                " VALUES (:feed, now(), :by)",
                {"feed": feed, "by": by},
            )
            for feed in ("vehicle_positions", "trip_updates", "gtfs_static")
            for by in ("pipeline", "detector")
        ],
        *[
            (
                "INSERT INTO ops.deploy (git_sha, previous_sha, outcome) VALUES (:sha, :prev, :o)",
                {"sha": "a" * 40, "prev": prev, "o": outcome},
            )
            for outcome in ("succeeded", "failed", "rollback_failed")
            for prev in (None, "b" * 40)
        ],
    ],
)
def test_ops_tables_accept_every_value_in_their_domain(
    empty_db: Engine, database_url: str, sql: str, params: dict[str, str | None]
) -> None:
    upgrade_to_head(database_url)
    with empty_db.begin() as con:
        con.execute(text(sql), params)


def test_recording_the_same_load_twice_is_rejected(empty_db: Engine, database_url: str) -> None:
    upgrade_to_head(database_url)
    row = _publish_run()
    with empty_db.begin() as con:
        con.execute(INSERT_RUN, row)
    with pytest.raises(IntegrityError), empty_db.begin() as con:
        con.execute(INSERT_RUN, row)


def test_finished_at_defaults_to_the_server_clock(empty_db: Engine, database_url: str) -> None:
    upgrade_to_head(database_url)
    with empty_db.begin() as con:
        con.execute(
            text(
                "INSERT INTO ops.publish_run (run_id, table_name, status, row_count, source,"
                " started_at) VALUES (:id, 'reliability', 'succeeded', 1, 'test', now())"
            ),
            {"id": uuid.uuid4()},
        )
        lag = con.execute(
            text("SELECT extract(epoch FROM clock_timestamp() - finished_at) FROM ops.publish_run")
        ).scalar_one()
    assert 0 <= lag < 60
