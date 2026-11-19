"""Currently announced cancellations (API spec section 4.1; ADR-029)."""

from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import Response

from ghostbus_api.problems import Problem
from ghostbus_api.repos import cancellations as repo
from ghostbus_api.repos import lines as line_repo
from ghostbus_api.routers._http import conditional, json_response
from ghostbus_api.schemas.cancellations import Cancellation, CurrentCancellations

router = APIRouter(prefix="/v1/cancellations")
LOCAL = ZoneInfo("America/Los_Angeles")


@router.get(
    "/current",
    response_model=CurrentCancellations,
    summary="Currently announced cancellations",
    description=(
        "Trips Metro's realtime feed marks canceled and hasn't shown as scheduled again, whose "
        "scheduled end is still ahead, as of `as_of` (the newest feed fetch; refreshed about "
        "every 10 minutes until M3). Filter with `line` (slug). Announced cancellations only: "
        "unplanned missed trips can't be known in advance."
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
            request, con, ("cancellation_current", "line", "line_direction"),
            {"_today": today.isoformat()},
        )  # fmt: skip
        if not_modified:
            return not_modified
        rows = repo.current(con, today, name)
    body = CurrentCancellations(
        as_of=rows[0]["as_of"] if rows else None,
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
