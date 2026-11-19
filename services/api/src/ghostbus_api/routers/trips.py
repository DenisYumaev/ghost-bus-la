"""Trip-level outcomes (API spec section 4.1)."""

from datetime import date
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from ghostbus_api import cursor
from ghostbus_api.problems import Problem
from ghostbus_api.repos import lines as line_repo
from ghostbus_api.repos import trips as repo
from ghostbus_api.routers._http import conditional, json_response
from ghostbus_api.schemas.trips import TripOutcome, TripOutcomes

router = APIRouter(prefix="/v1/trips")
LOCAL = ZoneInfo("America/Los_Angeles")


@router.get(
    "/outcomes",
    response_model=TripOutcomes,
    summary="Trip-level outcomes for one line and service date",
    description=(
        "Every scheduled trip of the line on the service date (last 35 days), ordered by "
        "scheduled start, with its outcome and whether it was announced. Paginate with "
        "`cursor` (from `next_cursor`) and `limit` (default 50, at most 200). A date outside "
        "the published window returns an empty list."
    ),
)
def trip_outcomes(
    request: Request,
    line: str,
    service_date: date,
    cursor_token: Annotated[str | None, Query(alias="cursor")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Response:
    with request.app.state.engine.connect() as con:
        found = line_repo.find_line(con, line, request.app.state.today())
        if found is None:
            raise Problem(404, "Line not found", f"No line '{line}'.")
        try:
            pos = cursor.decode(cursor_token) if cursor_token else None
        except cursor.BadCursor:
            raise Problem(400, "Bad cursor", "Use next_cursor from a previous page.") from None
        if pos and (pos.line, pos.service_date) != (found["line"], service_date):
            raise Problem(400, "Bad cursor", "This cursor belongs to another line or date.")
        after = (pos.sched_start, pos.trip_id) if pos else None
        as_of, headers, not_modified = conditional(request, con, ("trip_outcome_recent", "line"))
        if not_modified:
            return not_modified
        rows = repo.outcomes(con, str(found["line"]), service_date, after, limit + 1)
    page, more = rows[:limit], len(rows) > limit
    body = TripOutcomes(
        line=str(found["line"]),
        line_slug=str(found["line_slug"]),
        service_date=service_date,
        data_as_of=as_of,
        trips=[
            TripOutcome(
                trip_id=r["trip_id"],
                direction_id=r["direction_id"],
                sched_start=r["sched_start_utc"],
                sched_start_local=r["sched_start_utc"].astimezone(LOCAL).strftime("%H:%M"),
                outcome=r["outcome"],
                announced=r["announced"],
                advance_notice_s=r["advance_notice_s"],
                stop_coverage=r["stop_coverage"],
            )
            for r in page
        ],
        next_cursor=(
            cursor.encode(
                cursor.Position(
                    str(found["line"]),
                    service_date,
                    page[-1]["sched_start_utc"],
                    page[-1]["trip_id"],
                )
            )
            if more
            else None
        ),
    )
    return json_response(body, headers)
