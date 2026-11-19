"""Conditional responses shared by the public data endpoints (API spec section 3)."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from fastapi import Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import Connection

from ghostbus_api.caching import CACHE_CONTROL, etag_for, matches
from ghostbus_api.problems import Problem, ProblemDocument
from ghostbus_api.repos.lines import data_as_of

ERRORS = {
    400: "The cursor is malformed or belongs to another query.",
    404: "No such line.",
    422: "A parameter is missing or invalid; `errors` lists each one.",
    500: "Unexpected error. Quote `request_id` when reporting it.",
    503: "The database is unreachable, or nothing has been published yet.",
}
_HEADER = {"schema": {"type": "string"}}
CACHE_HEADERS = {
    "ETag": {**_HEADER, "description": "Send back in If-None-Match to get a 304."},
    "Cache-Control": _HEADER,
    "X-Request-Id": {**_HEADER, "description": "Echoed if sent and valid, else generated."},
}


def responses(*statuses: int, not_found: str | None = None) -> dict[int | str, dict[str, Any]]:
    """Every response an endpoint declares besides its body: the caching headers on 200 and
    304, the listed errors, and 500 and 503 for all. Error bodies are problem documents (API
    spec section 2). `not_found` describes this endpoint's 404."""
    declared: dict[int | str, dict[str, Any]] = {
        200: {"headers": CACHE_HEADERS},
        304: {
            "description": "Not modified: the ETag in If-None-Match is current.",
            "headers": CACHE_HEADERS,
        },
    }
    for status in (*statuses, 500, 503):
        description = not_found if status == 404 and not_found else ERRORS[status]
        declared[status] = {"model": ProblemDocument, "description": description}
    return declared


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
