"""In-process sliding-window rate limiter for expensive endpoints.

Single-instance only (documented in docs/SECURITY.md). A multi-instance deployment
should move this to Redis or the API gateway.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from app.errors import ApiError


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_s: float = 60.0) -> None:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                raise ApiError(429, "rate_limited",
                               f"Too many requests: limit is {limit} per minute for this action. Try again shortly.")
            q.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()
