"""HTTP caching for public data endpoints (API spec section 3)."""

import hashlib
from collections.abc import Mapping
from datetime import datetime

CACHE_CONTROL = "public, max-age=300, stale-while-revalidate=600"


def etag_for(data_as_of: datetime, path: str, query: Mapping[str, str]) -> str:
    """A strong ETag from the data's publish time plus the request: new data or another query
    gives a new tag. Query order doesn't matter."""
    key = "|".join([data_as_of.isoformat(), path, *(f"{k}={query[k]}" for k in sorted(query))])
    return '"' + hashlib.sha256(key.encode()).hexdigest()[:32] + '"'
