"""Small in-process sliding-window rate limiter.

Used per client IP (sign-in, password reset, token refresh) and per user (password
change, uploads, expensive jobs). Account-level lockout is stored in the database, so it
also holds across processes; these limiters are a second layer per API process (nginx
applies a per-IP limit in front of all of them) and need no Redis. With N API workers
the effective limit is up to N times the configured one.
"""

import threading
import time
from collections import defaultdict, deque

_ALL: list["SlidingWindowLimiter"] = []


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        _ALL.append(self)

    def hit(self, key: str) -> bool:
        """Record an attempt. Returns False when the key is over its limit."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            if len(self._hits) > 10_000:  # bound memory under abuse
                self._evict(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def _evict(self, now: float) -> None:
        for key in [k for k, v in self._hits.items() if not v or now - v[-1] > self.window]:
            del self._hits[key]


def reset_all_limiters() -> None:
    """Forget every recorded hit (used by the test suite between tests)."""
    for limiter in _ALL:
        limiter.reset()
