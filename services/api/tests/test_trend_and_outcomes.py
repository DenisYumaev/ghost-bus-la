"""GET /v1/lines/{line}/trend and GET /v1/trips/outcomes, served from the published dbt test
world (API spec sections 3 and 4.1; ADR-026)."""

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from ghostbus_api.main import create_app
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client(url: str) -> Iterator[TestClient]:
    app = create_app(url, today=lambda: date(2026, 11, 18))
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_the_trend_counts_back_from_the_newest_week_and_fills_gaps(client: TestClient) -> None:
    r = client.get("/v1/lines/2/trend", params={"direction_id": 1, "weeks": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["headsign"] == "Stop 2081"
    # Service date Nov 14 (a Saturday) is in the week starting Monday Nov 9: the newest week.
    assert [p["week_start"] for p in body["points"]] == ["2026-10-26", "2026-11-02", "2026-11-09"]
    empty, newest = body["points"][0], body["points"][-1]
    assert empty["n_trips"] is None
    assert empty["suppressed"] is True
    assert newest["n_scheduled"] == 1
    assert newest["suppressed"] is True  # one trip, one day (ADR-026)
    default = client.get("/v1/lines/2/trend", params={"direction_id": 1}).json()
    assert default["weeks"] == 12
    assert len(default["points"]) == 12


@pytest.mark.parametrize(
    "params", [{"direction_id": 1, "weeks": 0}, {"direction_id": 1, "weeks": 53}, {"weeks": 3}]
)
def test_trend_parameters_are_checked(client: TestClient, params: dict[str, int]) -> None:
    assert client.get("/v1/lines/2/trend", params=params).status_code == 422


def test_trip_outcomes_for_a_line_and_date(client: TestClient) -> None:
    r = client.get("/v1/trips/outcomes", params={"line": "2", "service_date": "2026-11-14"})
    assert r.status_code == 200
    body = r.json()
    assert body["line"] == "2"
    assert body["next_cursor"] is None
    [trip] = body["trips"]
    assert trip["trip_id"] == "T1-JUNE26"
    assert trip["outcome"] == "partial"
    assert trip["direction_id"] == 1
    assert trip["sched_start"].endswith("Z")
    assert len(trip["sched_start_local"]) == 5  # HH:MM in Los Angeles


def test_trip_outcomes_paginate_with_an_opaque_cursor(client: TestClient, url: str) -> None:
    engine = create_engine(url)
    with engine.begin() as con:  # three more trips on line 2 that day, out of order
        con.execute(text("""
            INSERT INTO serving.trip_outcome_recent
                (service_date, schedule_version, trip_id, line, direction_id, sched_start_utc,
                 outcome, announced)
            SELECT DATE '2026-11-13', 'cb1a2283abecc0af', trip_id, '2', 0, start, outcome, false
            FROM (VALUES ('X3', TIMESTAMPTZ '2026-11-13 20:00+00', 'ran'),
                         ('X1', TIMESTAMPTZ '2026-11-13 15:00+00', 'missed'),
                         ('X2', TIMESTAMPTZ '2026-11-13 20:00+00', 'ran'),
                         ('X0', TIMESTAMPTZ '2026-11-13 16:50+00', 'ran'))
                AS t(trip_id, start, outcome)
        """))  # fmt: skip
    engine.dispose()
    seen: list[str] = []
    # Its own date (Nov 13), so the other tests' Nov 14 rows are untouched.
    params: dict[str, object] = {"line": "2", "service_date": "2026-11-13", "limit": 2}
    tags: list[str] = []
    for _ in range(5):
        r = client.get("/v1/trips/outcomes", params=params)
        tags.append(r.headers["etag"])
        body = r.json()
        seen += [t["trip_id"] for t in body["trips"]]
        if body["next_cursor"] is None:
            break
        params["cursor"] = body["next_cursor"]
    # Ordered by scheduled start, then trip ID (X2 and X3 tie on start); nothing repeated.
    assert seen == ["X1", "X0", "X2", "X3"]
    assert len(set(tags)) == len(tags)  # each page has its own tag
    # A page's cursor can't be reused with another date or line.
    first = client.get("/v1/trips/outcomes", params={"line": "2", "service_date": "2026-11-13",
                                                      "limit": 1}).json()  # fmt: skip
    other_day = {"line": "2", "service_date": "2026-11-14", "cursor": first["next_cursor"]}
    assert client.get("/v1/trips/outcomes", params=other_day).status_code == 400
    other_line = {"line": "10-48", "service_date": "2026-11-13", "cursor": first["next_cursor"]}
    assert client.get("/v1/trips/outcomes", params=other_line).status_code == 400


def test_outcomes_and_trend_revalidate(client: TestClient) -> None:
    for path in ("/v1/trips/outcomes?line=2&service_date=2026-11-14",
                 "/v1/lines/2/trend?direction_id=1"):  # fmt: skip
        first = client.get(path)
        again = client.get(path, headers={"If-None-Match": first.headers["etag"]})
        assert again.status_code == 304, path


def test_a_date_outside_the_window_is_an_empty_list(client: TestClient) -> None:
    body = client.get("/v1/trips/outcomes", params={"line": "2", "service_date": "2025-01-01"})
    assert body.status_code == 200
    assert body.json()["trips"] == []


@pytest.mark.parametrize(
    ("params", "status"),
    [
        ({"line": "2", "service_date": "2026-11-14", "cursor": "garbage"}, 400),
        ({"line": "2", "service_date": "2026-11-14", "limit": 201}, 422),
        ({"line": "2"}, 422),
        ({"line": "999", "service_date": "2026-11-14"}, 404),
    ],
)
def test_trip_outcome_errors(client: TestClient, params: dict[str, object], status: int) -> None:
    r = client.get("/v1/trips/outcomes", params=params)
    assert r.status_code == status
    assert r.headers["content-type"] == "application/problem+json"
