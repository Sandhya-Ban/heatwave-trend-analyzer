"""Small in-process sliding-window rate limiter (per client IP + bucket)."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, window_s: int, clock=time.monotonic):
        self.window = window_s
        self.clock = clock
        self._hits: dict[tuple, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, ip: str, bucket: str, limit: int) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds)."""
        now = self.clock()
        with self._lock:
            if len(self._hits) > 20000:                       # bound memory under IP-spray
                for k in [k for k, q in self._hits.items() if not q or now - q[-1] > self.window]:
                    del self._hits[k]
            q = self._hits[(ip, bucket)]
            while q and now - q[0] >= self.window:
                q.popleft()
            if len(q) >= limit:
                return False, max(1, int(self.window - (now - q[0])) + 1)
            q.append(now)
            return True, 0
