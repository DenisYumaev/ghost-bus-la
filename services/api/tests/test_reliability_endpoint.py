"""GET /v1/lines/{line}/reliability end to end: the dbt test world, published into Postgres 16,
served through the app (API spec sections 1-4; ADR-007, ADR-013, ADR-028)."""

import os
from collections.abc import Iterator
from datetime import date

import pytest
from dbt_world import build_world, run_dbt
from fastapi.testclient import TestClient
from ghostbus_api.main import create_app
from ghostbus_api.migrations import downgrade_to_base, upgrade_to_head
from ghostbus_publish.engine import publish
from ghostbus_publish.tables import TABLES
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    url = os.environ.get("GHOSTBUS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("GHOSTBUS_TEST_DATABASE_URL not set (run make test-integration)")
    engine = create_engine(url)
    with engine.begin() as con:
        con.execute(text("DROP SCHEMA IF EXISTS serving, ops CASCADE"))
        con.execute(text("DROP TABLE IF EXISTS public.alembic_version"))
    engine.dispose()
    upgrade_to_head(url)
    tmp = tmp_path_factory.mktemp("api")
    publish(run_dbt(build_world(tmp), tmp), url, TABLES, source="test world")
    yield url
    downgrade_to_base(url)


TODAY = date(2026, 11, 18)


@pytest.fixture(scope="module")
def client(url: str) -> Iterator[TestClient]:
    with TestClient(create_app(url, today=lambda: TODAY), raise_server_exceptions=False) as client:
        yield client


@pytest.fixture(scope="module")
def versions(url: str) -> None:
    """Add schedule versions around the published one (in force since Nov 13):
    an old one, a future one starting tomorrow, and a same-day loser that was never in force.
    Each names line 2 differently, so the served name shows which version was picked. Also a
    lettered slug, a direction with a headsign but no cells, and a weekday cell before Sunday's.
    """
    engine = create_engine(url)
    with engine.begin() as con:
        con.execute(
            text("""
            INSERT INTO serving.schedule_version (version_id, valid_from, valid_to, ever_in_force)
            VALUES ('old', DATE '2026-06-01', DATE '2026-11-12', true),
                   ('future', DATE '2026-11-19', NULL, true),
                   ('loser', DATE '2026-11-13', DATE '2026-11-12', false);
            INSERT INTO serving.line (schedule_version, line, line_slug, display_name)
            VALUES ('old', '2', '2', 'Old 2'), ('future', '2', '2', 'Future 2'),
                   ('loser', '2', '2', 'Loser 2'),
                   ('cb1a2283abecc0af', 'Owl 7', 'owl-7', 'Owl 7');
            INSERT INTO serving.line_direction (schedule_version, line, direction_id, headsign)
            VALUES ('future', '2', 1, 'Future headsign'),
                   ('cb1a2283abecc0af', 'Owl 7', 0, 'Downtown'),
                   ('cb1a2283abecc0af', '2', 0, 'No cells this way');
            INSERT INTO serving.reliability (line, direction_id, time_window, day_type,
                                             hour_local, n_trips, suppressed)
            VALUES ('Owl 7', 0, '28d', 'sunday', 3, 4, true),
                   ('2', 1, '28d', 'weekday', 7, 2, true)""")
        )
    engine.dispose()


def test_a_line_direction_returns_its_grid(client: TestClient) -> None:  # before versions
    r = client.get("/v1/lines/2/reliability", params={"direction_id": 1})
    assert r.status_code == 200
    body = r.json()
    assert {k: body[k] for k in ("line", "line_slug", "display_name", "direction_id", "headsign",
                                 "window")} == {
        "line": "2", "line_slug": "2", "display_name": "2", "direction_id": 1,
        "headsign": "Stop 2081", "window": "28d",
    }  # fmt: skip
    assert body["data_as_of"].endswith("Z")
    assert body["data_through"] == "2026-11-14"
    # One trip on one day: counts, no rates, no interval (ADR-025).
    assert body["cells"] == [{
        "day_type": "sunday", "hour_local": 8, "n_trips": 1, "missed_rate": None,
        "announced_rate": None, "unplanned_rate": None, "ci_low": None, "ci_high": None,
        "suppressed": True,
    }]  # fmt: skip
    assert r.headers["cache-control"] == "public, max-age=300, stale-while-revalidate=600"
    assert r.headers["etag"]
    assert r.headers["x-request-id"]


def test_a_combined_line_is_addressed_by_its_slug(client: TestClient) -> None:
    r = client.get("/v1/lines/10-48/reliability", params={"direction_id": 0, "window": "all"})
    assert r.status_code == 200
    assert r.json()["line"] == "10/48"
    assert r.json()["window"] == "all"


def test_day_type_filters_the_cells(client: TestClient) -> None:
    r = client.get("/v1/lines/2/reliability", params={"direction_id": 1, "day_type": "saturday"})
    assert r.status_code == 200
    assert r.json()["cells"] == []
    # An empty grid still says which dates it covers.
    assert r.json()["data_through"] == "2026-11-14"
    assert r.json()["window_start"] == "2026-10-18"


def test_an_unknown_line_is_a_404_problem(client: TestClient) -> None:
    r = client.get("/v1/lines/999/reliability", params={"direction_id": 0})
    assert r.status_code == 404
    assert r.headers["content-type"] == "application/problem+json"
    body = r.json()
    assert body["status"] == 404
    assert body["title"] == "Line not found"
    assert body["type"].endswith("/problems/not-found")
    assert body["request_id"] == r.headers["x-request-id"]


def test_a_direction_without_data_is_a_404(client: TestClient) -> None:
    r = client.get("/v1/lines/2/reliability", params={"direction_id": 0})
    assert r.status_code == 404
    assert r.json()["title"] == "Direction not found"


@pytest.mark.parametrize(
    "params",
    [
        {"direction_id": 1, "window": "7d"},
        {"direction_id": 3},
        {},
        {"direction_id": 1, "day_type": "x"},
    ],
)
def test_bad_parameters_are_a_422_listing_the_fields(
    client: TestClient, params: dict[str, object]
) -> None:
    r = client.get("/v1/lines/2/reliability", params=params)
    assert r.status_code == 422
    assert r.headers["content-type"] == "application/problem+json"
    assert r.json()["errors"]


def test_an_unchanged_resource_is_a_304(client: TestClient) -> None:
    first = client.get("/v1/lines/2/reliability", params={"direction_id": 1})
    again = client.get(
        "/v1/lines/2/reliability",
        params={"direction_id": 1},
        headers={"If-None-Match": first.headers["etag"]},
    )
    assert again.status_code == 304
    assert again.content == b""
    assert again.headers["etag"] == first.headers["etag"]


def test_health_and_readiness(client: TestClient, url: str) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").status_code == 200
    engine = create_engine(url)
    with engine.begin() as con:  # make the newest publish two hours old
        con.execute(text("UPDATE ops.publish_run SET started_at = started_at - interval '2 hours', "
                         "finished_at = finished_at - interval '2 hours'"))  # fmt: skip
    engine.dispose()
    r = client.get("/readyz")
    assert r.status_code == 503
    assert r.headers["content-type"] == "application/problem+json"


def test_the_version_in_force_on_the_local_date_is_served(
    client: TestClient, versions: None
) -> None:
    body = client.get("/v1/lines/2/reliability", params={"direction_id": 1}).json()
    # Not the old one, not tomorrow's, not the never-in-force same-day loser.
    assert body["display_name"] == "2"
    assert body["headsign"] == "Stop 2081"
    # Cells come weekday first, then Sunday.
    assert [(c["day_type"], c["hour_local"]) for c in body["cells"]] == [
        ("weekday", 7), ("sunday", 8),
    ]  # fmt: skip


def test_a_lettered_slug_matches_in_any_case(client: TestClient, versions: None) -> None:
    r = client.get("/v1/lines/OWL-7/reliability", params={"direction_id": 0})
    assert r.status_code == 200
    assert r.json()["line"] == "Owl 7"


def test_a_direction_with_a_headsign_but_no_cells_is_a_404(
    client: TestClient, versions: None
) -> None:
    r = client.get("/v1/lines/2/reliability", params={"direction_id": 0})
    assert r.status_code == 404
    assert r.json()["title"] == "Direction not found"


def test_a_weak_etag_still_gets_a_304(client: TestClient) -> None:
    first = client.get("/v1/lines/10-48/reliability", params={"direction_id": 0})
    again = client.get(
        "/v1/lines/10-48/reliability",
        params={"direction_id": 0},
        headers={"If-None-Match": "W/" + first.headers["etag"]},
    )
    assert again.status_code == 304


def test_errors_carry_the_request_id_and_problem_shape(client: TestClient) -> None:
    r = client.post("/v1/lines/2/reliability")
    assert r.status_code == 405
    assert "GET" in r.headers["allow"]
    assert r.json()["type"].endswith("/problems/method-not-allowed")
    echoed = client.get("/healthz", headers={"X-Request-Id": "abcdef12-3456"})
    assert echoed.headers["x-request-id"] == "abcdef12-3456"
    hostile = client.get("/healthz", headers={"X-Request-Id": "x<script>"})
    assert hostile.headers["x-request-id"] != "x<script>"


def test_readiness_without_a_database_is_a_503() -> None:
    app = create_app("postgresql+psycopg://nobody:nothing@127.0.0.1:1/none")
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/readyz")
    assert r.status_code == 503
    assert r.json()["title"] == "Database unavailable"
    assert r.headers["x-request-id"]


def test_a_data_endpoint_without_a_database_is_a_503() -> None:
    app = create_app("postgresql+psycopg://nobody:nothing@127.0.0.1:1/none")
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/v1/lines/2/reliability", params={"direction_id": 1})
    assert r.status_code == 503
    assert r.headers["content-type"] == "application/problem+json"
    assert r.headers["x-request-id"]
