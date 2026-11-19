"""Response shapes for line reliability (API spec section 4.1)."""

from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, field_serializer

Window = Literal["28d", "90d", "all"]
DayType = Literal["weekday", "saturday", "sunday"]


class ReliabilityCell(BaseModel):
    day_type: DayType
    hour_local: int
    n_trips: int
    missed_rate: float | None
    announced_rate: float | None
    unplanned_rate: float | None
    # The 95% interval for missed_rate only (ADR-026, ADR-027).
    ci_low: float | None
    ci_high: float | None
    suppressed: bool


class LineReliability(BaseModel):
    model_config = {
        "json_schema_extra": {
            "examples": [{
                "line": "720", "line_slug": "720", "display_name": "720", "direction_id": 0,
                "headsign": "Santa Monica", "window": "28d", "window_start": "2026-11-04",
                "data_through": "2026-12-01", "data_as_of": "2026-12-01T17:40:12Z",
                "cells": [{
                    "day_type": "weekday", "hour_local": 17, "n_trips": 412,
                    "missed_rate": 0.051, "announced_rate": 0.024, "unplanned_rate": 0.027,
                    "ci_low": 0.038, "ci_high": 0.066, "suppressed": False,
                }],
                "method_url": "https://example.org/method",
            }]
        }
    }  # fmt: skip

    line: str
    line_slug: str
    display_name: str
    direction_id: int
    headsign: str
    window: Window
    window_start: date | None
    data_through: date | None
    data_as_of: datetime
    cells: list[ReliabilityCell]
    method_url: str

    @field_serializer("data_as_of")
    def _utc_z(self, value: datetime) -> str:
        # ISO 8601 in UTC with Z (API spec section 1).
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
