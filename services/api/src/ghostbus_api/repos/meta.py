"""Queries for the method page (API spec section 4.1)."""

from typing import Any

from sqlalchemy import Connection, text


def method_params(con: Connection) -> list[dict[str, Any]]:
    rows = con.execute(
        text(
            "SELECT name, value, unit, description, decision "
            "FROM serving.method_param ORDER BY name"
        )
    ).mappings()
    return [dict(r) for r in rows]
