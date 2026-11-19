"""GET /v1/cancellations/current (ADR-029), from the published dbt test world plus rows."""

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


def test_nothing_canceled_is_an_empty_list(client: TestClient) -> None:
    r = client.get("/v1/cancellations/current")
    assert r.status_code == 200
    assert r.json()["cancellations"] == []
    assert r.json()["as_of"] is None


def test_current_cancellations_with_names_and_a_line_filter(client: TestClient, url: str) -> None:
    engine = create_engine(url)
    with engine.begin() as con:
        con.execute(
            text("""
            INSERT INTO serving.cancellation_current
                (service_date, trip_id, line, direction_id, sched_start_utc, sched_end_utc,
                 canceled_first_seen_at, advance_notice_s, as_of)
            VALUES ('2026-11-18', 'B', '10/48', 0, '2026-11-18 22:00+00', '2026-11-18 23:00+00',
                    '2026-11-18 20:00+00', 7200, '2026-11-18 21:00+00'),
                   ('2026-11-18', 'A', '2', 1, '2026-11-18 21:30+00', '2026-11-18 22:30+00',
                    '2026-11-18 21:40+00', -600, '2026-11-18 21:00+00')""")
        )
    engine.dispose()
    body = client.get("/v1/cancellations/current").json()
    assert body["as_of"] == "2026-11-18T21:00:00Z"
    assert [(c["trip_id"], c["line_slug"]) for c in body["cancellations"]] == [
        ("A", "2"), ("B", "10-48"),
    ]  # fmt: skip
    first = body["cancellations"][0]
    assert first["headsign"] == "Stop 2081"
    assert first["sched_start_local"] == "13:30"
    assert first["advance_notice_s"] == -600
    only = client.get("/v1/cancellations/current", params={"line": "10-48"}).json()
    assert [c["trip_id"] for c in only["cancellations"]] == ["B"]
    assert client.get("/v1/cancellations/current", params={"line": "nope"}).status_code == 404
