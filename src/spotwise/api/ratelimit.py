"""Simple in-memory rate limit for /chat (API-06): N requests per minute per client IP.

Good enough for one server process. With several instances you would need a shared
store such as Redis, which is out of scope for v1.
"""

import threading
import time
from collections import deque
from collections.abc import Callable
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from spotwise.config import get_settings

WINDOW_S = 60.0


class RateLimiter:
    """Sliding window: allow at most `limit` requests per key in the last 60 seconds."""

    def __init__(self, limit: int, clock: Callable[[], float] = time.monotonic) -> None:
        self._limit = limit
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> int:
        """Record a request. Returns 0 if allowed, else seconds to wait."""
        now = self._clock()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - WINDOW_S:
                hits.popleft()
            if len(hits) >= self._limit:
                return max(1, int(hits[0] + WINDOW_S - now) + 1)
            hits.append(now)
            return 0


@lru_cache
def get_chat_rate_limiter() -> RateLimiter:
    """One shared limiter, configured by CHAT_RATE_LIMIT_PER_MIN."""
    return RateLimiter(get_settings().chat_rate_limit_per_min)


def enforce_chat_rate_limit(
    request: Request, limiter: Annotated[RateLimiter, Depends(get_chat_rate_limiter)]
) -> None:
    """FastAPI dependency: 429 with Retry-After when a client asks too often."""
    key = request.client.host if request.client else "unknown"
    wait = limiter.check(key)
    if wait:
        raise HTTPException(
            429, "Too many questions, please wait a moment.", headers={"Retry-After": str(wait)}
        )
