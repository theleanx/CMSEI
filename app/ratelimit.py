"""Sliding-window rate limiter keyed by client address. In process, so it protects one instance.
Behind several instances use a shared store (see README). The address is held in memory only and never logged."""
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self):
        self.hits = defaultdict(deque)
        self._last_gc = time.time()

    def allow(self, key: str, limit: int, window: float = 60.0) -> bool:
        now = time.time()
        q = self.hits[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        if now - self._last_gc > 300:
            self._gc(now, window)
        return True

    def _gc(self, now, window):
        for k in [k for k, q in self.hits.items() if not q or now - q[-1] > window]:
            self.hits.pop(k, None)
        self._last_gc = now


limiter = RateLimiter()
