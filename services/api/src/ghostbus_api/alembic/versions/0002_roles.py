"""Create the pipeline and api roles with least privilege (ADR-007 decision 5).

Roles are created NOLOGIN here: a migration never holds a password. The deploy turns on LOGIN
and sets each password from SSM (`python -m ghostbus_api.roles`). Roles are cluster-wide, so
the upgrade tolerates roles left from an earlier upgrade.

- `pipeline` creates (and so owns) every serving table, which the publish swap needs: only the
  owner can rename or drop a table. It records each publish in ops.publish_run.
- `api` reads serving and ops, nothing else. Serving tables are new objects on every publish,
  so plain grants would vanish at each swap; default privileges grant SELECT on every table
  `pipeline` creates in serving.

Roles are cluster-wide but this database is the cluster's only one (the VM, CI and local tests
each run their own Postgres), so the downgrade drops them. An adopted role is stripped of any
superuser, create or replication attribute it had. Serving tables that exist before this runs
are handed to `pipeline`, or its first swap would fail with "must be owner". Publish must run as
`pipeline` from then on (runbook). The detector role arrives with the detector (M3).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-20
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

UPGRADE = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'pipeline') THEN
        CREATE ROLE pipeline NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'api') THEN
        CREATE ROLE api NOLOGIN;
    END IF;
END
$$;
ALTER ROLE pipeline NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
ALTER ROLE api NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;

DO $$
DECLARE t record;
BEGIN
    FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'serving' LOOP
        EXECUTE format('ALTER TABLE serving.%I OWNER TO pipeline', t.tablename);
    END LOOP;
END
$$;

-- Nobody but the owner creates objects in public (PostgreSQL 15+ already revokes this).
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

GRANT USAGE, CREATE ON SCHEMA serving TO pipeline;
GRANT USAGE ON SCHEMA ops TO pipeline;
GRANT SELECT, INSERT ON ops.publish_run TO pipeline;
GRANT SELECT, INSERT, UPDATE ON ops.feed_status TO pipeline;

GRANT USAGE ON SCHEMA serving, ops TO api;
GRANT SELECT ON ALL TABLES IN SCHEMA ops TO api;
GRANT SELECT ON ALL TABLES IN SCHEMA serving TO api;
ALTER DEFAULT PRIVILEGES FOR ROLE pipeline IN SCHEMA serving GRANT SELECT ON TABLES TO api;
-- ops tables added by later migrations (created by this owner) are readable by api too.
ALTER DEFAULT PRIVILEGES IN SCHEMA ops GRANT SELECT ON TABLES TO api;
"""

DOWNGRADE = """
ALTER DEFAULT PRIVILEGES FOR ROLE pipeline IN SCHEMA serving REVOKE SELECT ON TABLES FROM api;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops REVOKE SELECT ON TABLES FROM api;
-- Serving tables the pipeline created belong to it; drop them so the role can go. Publish
-- rebuilds them from gold on its next run (ADR-007: serving holds no history).
DROP OWNED BY pipeline, api;
DROP ROLE IF EXISTS pipeline;
DROP ROLE IF EXISTS api;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
