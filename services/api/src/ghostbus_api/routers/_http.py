"""Conditional responses shared by the public data endpoints (API spec section 3)."""

from collections.abc import Mapping, Sequence
from datetime import datetime

from fastapi import Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import Connection

from ghostbus_api.caching import CACHE_CONTROL, etag_for, matches
from ghostbus_api.problems import Problem
from ghostbus_api.repos.lines import data_as_of


def conditional(
    request: Request, con: Connection, tables: Sequence[str], extra: Mapping[str, str] | None = None
) -> tuple[datetime, dict[str, str], Response | None]:
    """The main table's data_as_of, the caching headers, and a 304 response if the client's copy
    is current. The ETag covers every table the response reads plus `extra` (such as the
    schedule version in force), so any change to what the body shows changes the tag."""
    stamps = [data_as_of(con, t) for t in tables]
    if stamps[0] is None:
        raise Problem(503, "No published data yet")
    newest = max(s for s in stamps if s is not None)
    tag = etag_for(newest, request.url.path, dict(request.query_params) | dict(extra or {}))
    headers = {"ETag": tag, "Cache-Control": CACHE_CONTROL}
    if matches(request.headers.get("if-none-match"), tag):
        return stamps[0], headers, Response(status_code=304, headers=headers)
    return stamps[0], headers, None


def json_response(body: BaseModel, headers: Mapping[str, str]) -> Response:
    return Response(body.model_dump_json(), media_type="application/json", headers=dict(headers))
