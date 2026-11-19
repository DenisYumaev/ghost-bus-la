"""Shapes shared by several responses."""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import BaseModel, PlainSerializer

# ISO 8601 in UTC with Z (API spec section 1).
UtcTime = Annotated[
    datetime, PlainSerializer(lambda v: v.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
]


class Rates(BaseModel):
    """Counts and rates for a pooled group of trips (ADR-026). Intervals are 95% bootstrap
    intervals (ADR-027), null where the rate is suppressed or at 0 (or a share of 0 or 1)."""

    n_trips: int | None
    n_service_days: int | None
    missed_rate: float | None
    announced_rate: float | None
    unplanned_rate: float | None
    unplanned_share: float | None
    missed_rate_ci_low: float | None
    missed_rate_ci_high: float | None
    unplanned_share_ci_low: float | None
    unplanned_share_ci_high: float | None
    suppressed: bool | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any] | None) -> "Rates":
        """From a repository row (missing keys are null: a line with no summary yet)."""
        row = row or {}
        return cls.model_validate({k: row.get(k) for k in cls.model_fields})
