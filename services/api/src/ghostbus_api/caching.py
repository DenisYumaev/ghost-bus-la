"""HTTP caching for public data endpoints (API spec section 3)."""

import hashlib
from collections.abc import Mapping
from datetime import datetime

CACHE_CONTROL = "public, max-age=300, stale-while-revalidate=600"


def matches(if_none_match: str | None, tag: str) -> bool:
    """RFC 9110 section 13.1.2: weak comparison over a comma-separated list, or `*`. A proxy that
    compresses responses may turn our strong tag into W/"...", and must still get its 304."""
    if not if_none_match:
        return False
    candidates = [c.strip() for c in if_none_match.split(",")]
    return any(c == "*" or c.removeprefix("W/") == tag for c in candidates)


def etag_for(data_as_of: datetime, path: str, query: Mapping[str, str]) -> str:
    """A strong ETag from the data's publish time plus the request: new data or another query
    gives a new tag. Query order doesn't matter."""
    key = "|".join([data_as_of.isoformat(), path, *(f"{k}={query[k]}" for k in sorted(query))])
    return '"' + hashlib.sha256(key.encode()).hexdigest()[:32] + '"'
