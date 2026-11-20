"""GET /v1/meta/method: thresholds from the published build, plus definitions."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from ghostbus_api.main import create_app

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client(url: str) -> Iterator[TestClient]:
    with TestClient(create_app(url), raise_server_exceptions=False) as client:
        yield client


def test_the_method_page_shows_the_build_thresholds(client: TestClient) -> None:
    r = client.get("/v1/meta/method")
    assert r.status_code == 200
    body = r.json()
    thresholds = {t["name"]: t for t in body["thresholds"]}
    assert thresholds["min_stop_coverage"]["value"] == "0.8"
    assert thresholds["min_cell_service_days_weekend"]["value"] == "4"
    assert thresholds["min_cell_trips"]["decision"].startswith("ADR-025")
    assert thresholds["bootstrap_replicates"]["value"] == "2000"  # the nightly half
    assert thresholds["bootstrap_seed"]["value"] == "20261115"
    assert set(thresholds) == {
        "window_before_start_min", "window_after_end_min", "min_stop_coverage",
        "min_feed_healthy_share", "feed_fresh_max_s", "min_cell_trips",
        "min_cell_service_days_weekday", "min_cell_service_days_weekend", "min_week_service_days",
        "bootstrap_replicates", "bootstrap_seed",
    }  # fmt: skip
    text = " ".join(body["notes"] + [d["meaning"] for d in body["rates"]])
    assert "announced cancellation" in text
    assert "unplanned missed trip" in text
    assert "hid" not in text.lower()  # never imply Metro hides data (SPEC section 2.7)
    assert [d["term"] for d in body["outcomes"]] == ["ran", "partial", "unknown", "missed"]
    assert body["notes"][0] == "LA Bus Reliability is not affiliated with LA Metro."
    again = client.get("/v1/meta/method", headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304
