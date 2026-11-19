"""The OpenAPI contract (API spec section 9): the committed document matches the code, so any
API change shows up as a diff in review, and every endpoint documents itself fully (section 1).
Offline: building the document never connects to a database."""

import inspect
import re
from pathlib import Path
from typing import Any

import pytest
from ghostbus_api import openapi
from pydantic import BaseModel

COMMITTED = Path(__file__).resolve().parents[1] / "openapi.json"


def operations() -> list[tuple[str, dict[str, Any]]]:
    doc = openapi.document()
    return [(f"GET {path}", item["get"]) for path, item in doc["paths"].items()]


def test_the_committed_document_matches_the_code() -> None:
    assert COMMITTED.read_text() == openapi.render(), (
        "services/api/openapi.json is out of date: run `make openapi` and review the diff"
    )


def test_the_check_mode_reports_drift(tmp_path: Path) -> None:
    stale = tmp_path / "openapi.json"
    stale.write_text("{}\n")
    assert openapi.main(["--check", str(stale)]) == 1
    assert openapi.main(["--write", str(stale)]) == 0
    assert openapi.main(["--check", str(stale)]) == 0


def test_every_public_endpoint_is_documented() -> None:
    ops = operations()
    assert len(ops) == 10  # every M2 endpoint; health checks stay out of the document
    for name, op in ops:
        assert op.get("summary"), name
        assert op.get("description"), name


@pytest.mark.parametrize("status", ["304", "503"])
def test_every_endpoint_declares_not_modified_and_unavailable(status: str) -> None:
    for name, op in operations():
        assert status in op["responses"], name


def test_errors_are_problem_documents_not_fastapis_default() -> None:
    doc = openapi.document()
    assert "HTTPValidationError" not in doc["components"]["schemas"]
    for name, op in operations():
        for status, response in op["responses"].items():
            if status[0] in "45":
                assert set(response["content"]) == {"application/problem+json"}, (name, status)


def test_endpoints_with_a_line_declare_404() -> None:
    for name, op in operations():
        if "{line}" in name or any(p["name"] == "line" for p in op.get("parameters", [])):
            assert "404" in op["responses"], name


def response_models() -> list[type[BaseModel]]:
    # Each router's own routes: the app wraps included routers, hiding their models.
    from ghostbus_api.routers import cancellations, lines, meta, system, trips

    modules = (cancellations, lines, meta, system, trips)
    return [r.response_model for m in modules for r in m.router.routes if r.response_model]


def test_every_status_a_route_raises_is_declared() -> None:
    # A new `raise Problem(409, ...)` must reach the document too. Statuses raised by shared
    # helpers: `_find` (404) and `conditional` (503, always declared).
    from ghostbus_api.routers import cancellations, lines, meta, system, trips

    for module in (cancellations, lines, meta, system, trips):
        for route in module.router.routes:
            source = inspect.getsource(route.endpoint)
            raised = {int(s) for s in re.findall(r"Problem\((\d{3})", source)}
            if "_find(" in source:
                raised.add(404)
            declared = {int(s) for s in route.responses}
            assert raised <= declared, (route.path, raised - declared)


def test_every_success_response_has_an_example_that_validates() -> None:
    # An example that drifts from its model is caught here, not by a confused web developer.
    models = response_models()
    assert len(models) == 10
    for model in models:
        examples = model.model_json_schema().get("examples")  # what the document shows
        assert examples, model.__name__
        for example in examples:
            # Round trip: validation ignores unknown keys at any depth, so compare the dump too.
            # That catches a stale nested key and a timestamp not in UTC-with-Z form.
            assert model.model_validate(example).model_dump(mode="json") == example, model
