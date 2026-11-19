"""RFC 9457 problem details for every error (API spec section 2), plus request IDs. Never a
stack trace."""

import logging
import re
import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SATimeoutError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("ghostbus_api")
REQUEST_ID = re.compile(r"[A-Za-z0-9-]{8,64}")
SLUGS = {
    400: "bad-request", 404: "not-found", 405: "method-not-allowed", 422: "validation",
    500: "internal", 503: "unavailable",
}  # fmt: skip


class Problem(Exception):
    """Raise to answer with a problem document."""

    def __init__(self, status: int, title: str, detail: str = "") -> None:
        super().__init__(title)
        self.status, self.title, self.detail = status, title, detail


def problem_response(
    request: Request,
    status: int,
    title: str,
    detail: str = "",
    headers: Mapping[str, str] | None = None,
    **extra: Any,
) -> JSONResponse:
    site = request.app.state.settings.site_url
    request_id = getattr(request.state, "request_id", None) or uuid.uuid4().hex
    body = {
        "type": f"{site}/problems/{SLUGS.get(status, 'error')}",
        "title": title,
        "status": status,
        "detail": detail,
        "request_id": request_id,
        **extra,
    }
    # Set here too: an unhandled error's response is built outside the request-id middleware.
    all_headers = {"X-Request-Id": request_id, **(headers or {})}
    return JSONResponse(
        body, status_code=status, media_type="application/problem+json", headers=all_headers
    )


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request.state.request_id = incoming if REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex
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
        # 422 covers malformed and invalid parameters alike (API spec section 2).
        return problem_response(request, 422, "Invalid parameters", errors=errors)

    @app.exception_handler(StarletteHTTPException)
    async def on_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Keeps headers such as Allow on a 405.
        return problem_response(request, exc.status_code, str(exc.detail), headers=exc.headers)

    @app.exception_handler(OperationalError)
    @app.exception_handler(SATimeoutError)
    async def on_database_down(request: Request, exc: Exception) -> JSONResponse:
        log.warning("database unavailable, request %s: %s", request.state.request_id, type(exc))
        return problem_response(request, 503, "Database unavailable")

    @app.exception_handler(Exception)
    async def on_error(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error, request %s", request.state.request_id)
        return problem_response(request, 500, "Internal error")
