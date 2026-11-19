"""The line list, line detail, stops, system summary and feed health endpoints, served from the
published dbt test world (API spec section 4.1)."""

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from ghostbus_api.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client(url: str) -> Iterator[TestClient]:
    app = create_app(url, today=lambda: date(2026, 11, 18))
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_the_line_list_orders_by_number_and_pools_directions(client: TestClient) -> None:
    r = client.get("/v1/lines")
    assert r.status_code == 200
    body = r.json()
    assert body["window"] == "28d"
    assert body["data_through"] == "2026-11-14"
    assert [(x["line"], x["line_slug"]) for x in body["lines"]] == [("2", "2"), ("10/48", "10-48")]
    first = body["lines"][0]["summary"]
    assert first["n_trips"] == 1
    assert first["suppressed"] is True
    assert first["missed_rate"] is None
    assert r.headers["etag"]


def test_line_detail_has_directions_with_headsigns_and_summaries(client: TestClient) -> None:
    body = client.get("/v1/lines/2").json()
    assert body["line"] == "2"
    assert body["data_through"] == "2026-11-14"
    assert [(d["direction_id"], d["headsign"]) for d in body["directions"]] == [(1, "Stop 2081")]
    assert body["directions"][0]["summary"]["n_trips"] == 1
    assert body["summary"]["n_trips"] == 1  # both directions pooled
    assert client.get("/v1/lines/nope").status_code == 404


def test_stops_come_in_route_order(client: TestClient) -> None:
    r = client.get("/v1/lines/2/stops", params={"direction_id": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["headsign"] == "Stop 2081"
    orders = [s["stop_order"] for s in body["stops"]]
    assert orders == [1, 2, 3]  # T1's three stops
    assert body["stops"][-1]["stop_name"] == "Stop 2081"
    one = client.get("/v1/lines/10-48/stops", params={"direction_id": 0}).json()
    assert one["line"] == "10/48"
    assert client.get("/v1/lines/10-48/stops", params={"direction_id": 1}).status_code == 404
    assert client.get("/v1/lines/10-48/stops").status_code == 422


def test_the_system_summary_has_every_window(client: TestClient) -> None:
    body = client.get("/v1/system/summary").json()
    assert [w["window"] for w in body["windows"]] == ["28d", "90d", "all"]
    assert all(w["n_lines"] == 2 for w in body["windows"])
    assert body["windows"][0]["rates"]["suppressed"] is True
    assert body["data_as_of"].endswith("Z")


def test_feed_health_returns_the_last_hours(client: TestClient) -> None:
    body = client.get("/v1/system/feed-health", params={"hours": 2}).json()
    feeds = {b["feed"] for b in body["buckets"]}
    assert feeds == {"vehicle_positions", "trip_updates"}
    assert len(body["buckets"]) == 2 * 24  # 2 hours of 5-minute buckets, 2 feeds
    assert body["buckets"][0]["bucket_start"].endswith("Z")
    assert client.get("/v1/system/feed-health", params={"hours": 169}).status_code == 422


def test_every_new_endpoint_is_cacheable(client: TestClient) -> None:
    for path in ("/v1/lines", "/v1/lines/2", "/v1/system/summary", "/v1/system/feed-health"):
        first = client.get(path)
        again = client.get(path, headers={"If-None-Match": first.headers["etag"]})
        assert again.status_code == 304, path
