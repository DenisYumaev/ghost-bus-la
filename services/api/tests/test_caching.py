"""ETags (API spec section 3): stable for the same data and query, different otherwise."""

from datetime import UTC, datetime

from ghostbus_api.caching import etag_for
from ghostbus_api.repos.lines import normalize_slug

AS_OF = datetime(2026, 11, 18, 17, 40, 12, tzinfo=UTC)


def test_same_data_and_query_same_etag() -> None:
    a = etag_for(AS_OF, "/v1/lines/2/reliability", {"direction_id": "1", "window": "28d"})
    b = etag_for(AS_OF, "/v1/lines/2/reliability", {"window": "28d", "direction_id": "1"})
    assert a == b
    assert a.startswith('"')
    assert a.endswith('"')


def test_new_data_or_another_query_changes_it() -> None:
    base = etag_for(AS_OF, "/v1/lines/2/reliability", {"direction_id": "1"})
    later = AS_OF.replace(minute=50)
    assert etag_for(later, "/v1/lines/2/reliability", {"direction_id": "1"}) != base
    assert etag_for(AS_OF, "/v1/lines/2/reliability", {"direction_id": "0"}) != base
    assert etag_for(AS_OF, "/v1/lines/3/reliability", {"direction_id": "1"}) != base


def test_slugs_are_matched_case_insensitively() -> None:
    assert normalize_slug("Dodger-Stadium-Express") == "dodger-stadium-express"
    assert normalize_slug(" 10-48 ") == "10-48"
