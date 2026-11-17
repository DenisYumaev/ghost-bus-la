"""Create the serving and ops schemas and the ops tables (ADR-007; API spec section 7).

Serving tables are created by publish on every load (ADR-007 decision 3), so only the schema
is made here. The app schema arrives with alerts (M3).

Revision ID: 0001
Revises:
Create Date: 2026-11-17
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

UPGRADE = """
CREATE SCHEMA serving;
CREATE SCHEMA ops;

-- One row per serving table per publish attempt, written by publish inside the swap
-- transaction. data_as_of = the latest succeeded row's finished_at for that table (API spec
-- section 1); finished_at defaults to the server clock so a client clock can't backdate or
-- future-date it. Readers that only need "did anything advance?" poll max(id). A publish that
-- crashes mid-load writes no row; the job's logs and failure alert cover that case.
CREATE TABLE ops.publish_run (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id      uuid NOT NULL,             -- groups the tables of one publish invocation
    table_name  text NOT NULL
                CHECK (table_name ~ '^[a-z][a-z0-9_]*$' AND table_name !~ '__(new|old)$'),
    status      text NOT NULL CHECK (status IN ('succeeded', 'failed')),
    row_count   bigint CHECK (row_count >= 0),
    source      text NOT NULL CHECK (btrim(source) <> ''),  -- which partitions, e.g. a date range
    started_at  timestamptz NOT NULL,
    finished_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    error       text CHECK (error IS NULL OR btrim(error) <> ''),
    CHECK (finished_at >= started_at),
    CHECK ((status = 'succeeded') = (error IS NULL)),
    CHECK (status <> 'succeeded' OR row_count IS NOT NULL),
    UNIQUE (run_id, table_name)  -- recording the same load twice is a no-op (hard rule 2)
);
CREATE INDEX publish_run_latest_idx ON ops.publish_run (table_name, finished_at DESC)
    WHERE status = 'succeeded';

-- Where a stream consumer (the detector, M3) has got to; one row per consumer.
CREATE TABLE ops.consumer_cursor (
    consumer   text PRIMARY KEY,
    position   text NOT NULL CHECK (position <> ''),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Latest successful fetch per feed, for /readyz and the status page. Written by the detector
-- and the pipeline, never by ingest (hard rule 3: ingest needs no Postgres).
CREATE TABLE ops.feed_status (
    feed            text PRIMARY KEY
                    CHECK (feed IN ('vehicle_positions', 'trip_updates', 'gtfs_static')),
    last_success_at timestamptz NOT NULL,
    last_feed_ts    timestamptz,           -- newest entity timestamp in that snapshot
    updated_by      text NOT NULL CHECK (updated_by IN ('detector', 'pipeline')),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- One row per deploy (infra spec section 6, step 5). 'failed' means the deploy failed and the
-- previous SHA was redeployed (step 4); 'rollback_failed' means that redeploy failed too.
CREATE TABLE ops.deploy (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    git_sha      text NOT NULL CHECK (git_sha ~ '^[0-9a-f]{40}$'),
    previous_sha text CHECK (previous_sha ~ '^[0-9a-f]{40}$'),  -- NULL on the first deploy
    outcome      text NOT NULL CHECK (outcome IN ('succeeded', 'failed', 'rollback_failed')),
    deployed_at  timestamptz NOT NULL DEFAULT now()
);
"""

DOWNGRADE = """
DROP SCHEMA ops CASCADE;
DROP SCHEMA serving CASCADE;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
