"""The method page: thresholds from this build, and the definitions behind every number."""

import hashlib

from fastapi import APIRouter, Request
from fastapi.responses import Response

from ghostbus_api.repos import meta as repo
from ghostbus_api.routers._http import conditional, json_response, responses
from ghostbus_api.schemas.meta import Definition, Method, Threshold

router = APIRouter(prefix="/v1/meta")

# Pipeline spec section 8 and ADR-024: the outcome of each scheduled trip, first match wins.
OUTCOMES = [
    Definition(term="ran", meaning="Seen running at or after its scheduled start, and reached at "
               "least the minimum share of its stops."),
    Definition(term="partial", meaning="Seen running, but stopped short of the minimum share of "
               "its stops, or seen only through trip predictions. Never counted as missed."),
    Definition(term="unknown", meaning="Not seen, while the realtime feeds were unhealthy for "
               "too much of the trip's window, or had no data for it. Left out of every rate."),
    Definition(term="missed", meaning="Not seen while the feeds were healthy."),
]  # fmt: skip

RATES = [
    Definition(term="missed_rate", meaning="Missed trips divided by scheduled trips minus "
               "unknown ones (n_trips)."),
    Definition(term="announced_rate", meaning="Missed trips Metro's realtime feed marked canceled "
               "as of their scheduled start (an announced cancellation), divided by n_trips."),
    Definition(term="unplanned_rate", meaning="Missed trips not marked canceled as of their "
               "scheduled start (an unplanned missed trip; a cancellation withdrawn before "
               "departure doesn't count), divided by n_trips."),
    Definition(term="unplanned_share", meaning="Unplanned missed trips divided by all missed "
               "trips."),
]  # fmt: skip

NOTES = [
    "LA Bus Reliability is not affiliated with LA Metro.",
    "An announced cancellation is a trip marked canceled in Metro's realtime feed as of its "
    "scheduled start. An unplanned missed trip is one never seen running and not marked canceled "
    "by then. What the canceled flag covers isn't documented, so no claim is made about why a "
    "trip wasn't marked.",
    "Intervals are 95% intervals from resampling whole service days within each day type, "
    "because trips on one day share causes. They are shown for missed rates (and, on line and "
    "system summaries, for the unplanned share), are refreshed nightly, and are left out where "
    "a rate is 0 or a share is 0 or 1.",
    "A holiday with Sunday service counts as a Sunday. A trip after midnight belongs to the "
    "service day it began: Friday's 1:30 AM bus counts in Friday's (weekday) numbers, at hour 1.",
    "Limitations: a bus running without a working tracker may be counted as missed until block "
    "matching lands; contracted lines are not yet separated from Metro-operated ones; a trip cut "
    "short or detoured counts as partial, never as missed.",
]


STATIC_VERSION = hashlib.sha256(repr((OUTCOMES, RATES, NOTES)).encode()).hexdigest()[:16]


@router.get(
    "/method",
    response_model=Method,
    responses=responses(),
    summary="Thresholds and definitions currently in force",
    description=(
        "The thresholds come from the same build as the numbers; the definitions follow the "
        "pipeline specification's decision table."
    ),
)
def method(request: Request) -> Response:
    with request.app.state.engine.connect() as con:
        # The definitions live in code: a deploy that changes them must change the tag too.
        as_of, headers, not_modified = conditional(
            request, con, ("method_param",), {"_text": STATIC_VERSION}
        )
        if not_modified:
            return not_modified
        rows = repo.method_params(con)
    body = Method(
        data_as_of=as_of, thresholds=[Threshold(**r) for r in rows],
        outcomes=OUTCOMES, rates=RATES, notes=NOTES,
    )  # fmt: skip
    return json_response(body, headers)
