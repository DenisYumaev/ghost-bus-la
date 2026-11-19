"""Currently announced cancellations (API spec section 4.1; ADR-029)."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import Response

from ghostbus_api.problems import Problem
from ghostbus_api.repos import cancellations as repo
from ghostbus_api.repos import lines as line_repo
from ghostbus_api.routers._http import conditional, json_response, responses
from ghostbus_api.schemas.cancellations import Cancellation, CurrentCancellations

router = APIRouter(prefix="/v1/cancellations")
SHORT_CACHE = "public, max-age=60, stale-while-revalidate=60"
# Data can lag up to about an hour (hourly fetch-log upload, ADR-029); older than this means the
# pipeline has stalled, and the page must say so rather than show an old list as current.
STALE_AFTER = timedelta(minutes=90)
LOCAL = ZoneInfo("America/Los_Angeles")


@router.get(
    "/current",
    response_model=CurrentCancellations,
    # `line` can't fail validation, but FastAPI documents a 422 for any endpoint with
    # parameters; declaring ours keeps its default shape out of the document.
    responses=responses(404, 422),
    summary="Currently announced cancellations",
    description=(
        "Trips Metro's realtime feed marks canceled and hasn't shown as scheduled again, whose "
        "scheduled end is still ahead, as of `as_of`: the newest feed fetch the data covers, "
        "which can be up to about an hour old until M3. Filter with `line` (slug). Announced "
        "cancellations only: unplanned missed trips can't be known in advance."
    ),
)
def current_cancellations(request: Request, line: str | None = None) -> Response:
    today = request.app.state.today()
    with request.app.state.engine.connect() as con:
        name = None
        if line is not None:
            found = line_repo.find_line(con, line, today)
            if found is None:
                raise Problem(404, "Line not found", f"No line '{line}'.")
            name = str(found["line"])
        as_of_publish, headers, not_modified = conditional(
            request, con, ("cancellation_current", "cancellation_as_of", "line", "line_direction"),
        )  # fmt: skip
        if not_modified:
            return not_modified
        rows = repo.current(con, name)
        fetched = repo.as_of(con)
    # A short cache: this list changes within minutes (the others change nightly).
    headers = headers | {"Cache-Control": SHORT_CACHE}
    stale = fetched is None or datetime.now(UTC) - fetched > STALE_AFTER
    body = CurrentCancellations(
        as_of=fetched,
        stale=stale,
        data_as_of=as_of_publish,
        cancellations=[
            Cancellation(
                service_date=r["service_date"], trip_id=r["trip_id"], line=r["line"],
                line_slug=r["line_slug"], display_name=r["display_name"],
                direction_id=r["direction_id"], headsign=r["headsign"],
                sched_start=r["sched_start_utc"],
                sched_start_local=r["sched_start_utc"].astimezone(LOCAL).strftime("%H:%M"),
                first_seen_at=r["canceled_first_seen_at"], advance_notice_s=r["advance_notice_s"],
            )
            for r in rows
        ],
    )  # fmt: skip
    return json_response(body, headers)
