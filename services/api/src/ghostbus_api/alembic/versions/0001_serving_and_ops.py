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

-- One row per serving table per publish attempt. data_as_of = the latest succeeded row's
-- finished_at for that table (API spec section 1).
CREATE TABLE ops.publish_run (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id      uuid NOT NULL,             -- groups the tables of one publish invocation
    table_name  text NOT NULL,
    status      text NOT NULL CHECK (status IN ('succeeded', 'failed')),
    row_count   bigint CHECK (row_count >= 0),
    source      text NOT NULL,             -- which partitions were loaded, e.g. the date range
    started_at  timestamptz NOT NULL,
    finished_at timestamptz NOT NULL,
    error       text,
    CHECK (finished_at >= started_at),
    CHECK ((status = 'succeeded') = (error IS NULL)),
    CHECK (status <> 'succeeded' OR row_count IS NOT NULL)
);
CREATE INDEX publish_run_latest_idx ON ops.publish_run (table_name, finished_at DESC)
    WHERE status = 'succeeded';

-- Where a stream consumer (the detector, M3) has got to; one row per consumer.
CREATE TABLE ops.consumer_cursor (
    consumer   text PRIMARY KEY,
    position   text NOT NULL,
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

-- One row per deploy (infra spec section 6, step 5).
CREATE TABLE ops.deploy (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    git_sha     text NOT NULL CHECK (git_sha ~ '^[0-9a-f]{40}$'),
    outcome     text NOT NULL CHECK (outcome IN ('succeeded', 'rolled_back')),
    deployed_at timestamptz NOT NULL DEFAULT now()
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
