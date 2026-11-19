"""Current cancellations (API spec section 4.1; ADR-029)."""

from datetime import date

from pydantic import BaseModel

from ghostbus_api.schemas.common import UtcTime


class Cancellation(BaseModel):
    service_date: date
    trip_id: str
    line: str
    line_slug: str | None
    display_name: str | None
    direction_id: int | None
    headsign: str | None
    sched_start: UtcTime
    sched_start_local: str  # HH:MM in Los Angeles
    first_seen_at: UtcTime
    advance_notice_s: float | None


class CurrentCancellations(BaseModel):
    as_of: UtcTime | None  # the newest feed fetch these reflect; null if none published yet
    data_as_of: UtcTime
    cancellations: list[Cancellation]
