"""A sliding-window rate limit per key (a client address, say). Per process, reset on restart, like the agent's."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable


class SlidingWindowLimit:
    """At most `limit` hits per key in any `window_s` seconds; 0 turns it off."""

    def __init__(self, limit: int, window_s: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self.limit = limit
        self.window_s = window_s
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._mutex = threading.Lock()

    def allow(self, key: str) -> tuple[bool, float]:
        """(allowed, seconds until the next hit would be). Counts the hit when it is allowed."""
        if not self.limit:
            return True, 0.0
        with self._mutex:
            now = self._clock()
            for k in list(self._hits):  # forget old hits, and keys with none left
                hits = self._hits[k]
                while hits and now - hits[0] >= self.window_s:
                    hits.popleft()
                if not hits:
                    del self._hits[k]
            hits = self._hits.setdefault(key, deque())
            if len(hits) >= self.limit:
                return False, max(0.0, self.window_s - (now - hits[0]))
            hits.append(now)
            return True, 0.0
