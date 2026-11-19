"""RFC 9457 problem details for every error (API spec section 2), plus request IDs. Never a
stack trace."""

import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("ghostbus_api")
REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
SLUGS = {400: "bad-request", 404: "not-found", 422: "validation", 503: "unavailable"}


class Problem(Exception):
    """Raise to answer with a problem document."""

    def __init__(self, status: int, title: str, detail: str = "") -> None:
        super().__init__(title)
        self.status, self.title, self.detail = status, title, detail


def problem_response(
    request: Request, status: int, title: str, detail: str = "", **extra: Any
) -> JSONResponse:
    site = request.app.state.settings.site_url
    body = {
        "type": f"{site}/problems/{SLUGS.get(status, 'error')}",
        "title": title,
        "status": status,
        "detail": detail,
        "request_id": request.state.request_id,
        **extra,
    }
    return JSONResponse(body, status_code=status, media_type="application/problem+json")


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request.state.request_id = incoming if REQUEST_ID.match(incoming) else uuid.uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.request_id
        return response

    @app.exception_handler(Problem)
    async def on_problem(request: Request, exc: Problem) -> JSONResponse:
        return problem_response(request, exc.status, exc.title, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def on_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]}
            for e in exc.errors()
        ]
        return problem_response(request, 422, "Invalid parameters", errors=errors)

    @app.exception_handler(StarletteHTTPException)
    async def on_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return problem_response(request, exc.status_code, str(exc.detail))

    @app.exception_handler(Exception)
    async def on_error(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error, request %s", request.state.request_id)
        return problem_response(request, 500, "Internal error")
