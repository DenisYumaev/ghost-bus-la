"""Integration fixtures: Postgres 16 from compose.test.yml; skipped without it (offline)."""

import os

import pytest


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("GHOSTBUS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("GHOSTBUS_TEST_DATABASE_URL not set (run make test-integration)")
    return url
