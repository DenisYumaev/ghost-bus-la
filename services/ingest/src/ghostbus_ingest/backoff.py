"""Exponential backoff with jitter, for reconnecting and for retrying S3 (spec 2.3).

The schedule is 1, 2, 4, 8, ... seconds, capped at 60. Each delay is then scaled by a random
factor between 0.5 and 1 ("jitter"), so that many clients retrying after the same outage don't
all hit the server at the same instant.
"""

import random
from collections.abc import Callable

BASE_S = 1.0
CAP_S = 60.0


def backoff_delay(
    attempt: int,
    base_s: float = BASE_S,
    cap_s: float = CAP_S,
    rand: Callable[[], float] = random.random,  # timing jitter, not security
) -> float:
    """Seconds to wait before retry number `attempt` (0 for the first retry)."""
    if attempt < 0:
        raise ValueError(f"attempt must be >= 0, got {attempt}")
    # The exponent is capped so a long outage (attempt 10,000) can't overflow a float.
    delay = min(cap_s, base_s * 2.0 ** min(attempt, 32))
    return delay * (0.5 + 0.5 * rand())
