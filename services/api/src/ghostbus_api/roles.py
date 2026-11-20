"""Turn on login for the pipeline and api roles and set their passwords (ADR-007 decision 5).

    python -m ghostbus_api.roles

Run by the deploy after the migrations, as the database owner (GHOSTBUS_DATABASE_URL). The
passwords come from the environment (GHOSTBUS_PIPELINE_DB_PASSWORD, GHOSTBUS_API_DB_PASSWORD),
which the deploy fills from SSM. Never from argv, never printed. Safe to run on every deploy:
setting the same password again changes nothing.
"""

import os
import sys
from collections.abc import Mapping

import psycopg
from psycopg import sql
from sqlalchemy.exc import SQLAlchemyError

from ghostbus_api.db import make_engine

ROLES = {"pipeline": "GHOSTBUS_PIPELINE_DB_PASSWORD", "api": "GHOSTBUS_API_DB_PASSWORD"}
MIN_PASSWORD_LENGTH = 24


def passwords_from(env: Mapping[str, str]) -> dict[str, str]:
    """Each role's password, refusing a missing or short one."""
    found = {}
    for role, name in ROLES.items():
        value = env.get(name, "")
        if len(value) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"{name} is missing or shorter than {MIN_PASSWORD_LENGTH} characters")
        found[role] = value
    return found


def set_passwords(database_url: str, passwords: Mapping[str, str]) -> None:
    engine = make_engine(database_url)
    try:
        connection = engine.raw_connection()
        try:
            pgconn = connection.driver_connection.pgconn  # type: ignore[union-attr]
            cur = connection.cursor()
            for role, password in passwords.items():
                # Hashed here (SCRAM): the plaintext never reaches the server, so it can't show up
                # in pg_stat_activity or in a logged failed statement.
                verifier = pgconn.encrypt_password(
                    password.encode(), role.encode(), b"scram-sha-256"
                ).decode()
                cur.execute(
                    sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(
                        sql.Identifier(role), sql.Literal(verifier)
                    )
                )
            cur.close()
            connection.commit()
        finally:
            connection.close()
    finally:
        engine.dispose()


def main() -> int:
    url = os.environ.get("GHOSTBUS_DATABASE_URL")
    if not url:
        print("set GHOSTBUS_DATABASE_URL", file=sys.stderr)
        return 2
    try:
        set_passwords(url, passwords_from(os.environ))
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    except (SQLAlchemyError, psycopg.Error):
        # libpq errors can quote connection details; keep them out of the deploy log.
        print("could not set role passwords (details withheld)", file=sys.stderr)
        return 1
    print(f"login enabled for roles: {', '.join(ROLES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
