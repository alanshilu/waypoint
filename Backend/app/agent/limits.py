"""
The agent's cost limits for a public demo: messages per minute per session, new sessions per address per
hour, and agent turns per UTC day across everyone. 0 turns a limit off. Kept apart from the session store:
storing conversations and rationing them are separate jobs, and either can change without the other.
Like the in-memory sessions, the counters are per process and reset on restart.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Protocol


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentLimits(Protocol):
    """Each check counts the request when it allows it, and returns (allowed, retry_after_s)."""

    def allow_message(self, session_id: str) -> tuple[bool, float]: ...
    def allow_new_session(self, client_ip: str) -> tuple[bool, float]: ...
    def take_turn(self) -> tuple[bool, float]: ...


def _prune(windows: dict[str, deque[float]], now: float, window_s: float) -> None:
    """Drops hits older than the window, and keys with none left."""
    for key in list(windows):
        hits = windows[key]
        while hits and now - hits[0] >= window_s:
            hits.popleft()
        if not hits:
            del windows[key]


class InMemoryLimits:
    """Sliding windows per session (a minute) and per address (an hour), and a counter per UTC day."""

    def __init__(self, rate_per_minute: int, *, sessions_per_ip_per_hour: int = 0, daily_turn_cap: int = 0,
                 clock: Callable[[], float] = time.monotonic, utc_now: Callable[[], datetime] = _utc_now):
        self.rate_per_minute = rate_per_minute
        self.sessions_per_ip_per_hour = sessions_per_ip_per_hour
        self.daily_turn_cap = daily_turn_cap
        self._clock = clock
        self._utc_now = utc_now
        self._message_hits: dict[str, deque[float]] = {}
        self._ip_hits: dict[str, deque[float]] = {}
        self._turn_day = None
        self._turns_today = 0
        self._mutex = threading.Lock()

    def allow_message(self, session_id: str) -> tuple[bool, float]:
        """One more message on this session this minute."""
        if not self.rate_per_minute:
            return True, 0.0
        with self._mutex:
            now = self._clock()
            _prune(self._message_hits, now, 60)  # also forgets expired sessions' windows
            hits = self._message_hits.setdefault(session_id, deque())
            if len(hits) >= self.rate_per_minute:
                return False, max(0.0, 60 - (now - hits[0]))
            hits.append(now)
            return True, 0.0

    def allow_new_session(self, client_ip: str) -> tuple[bool, float]:
        """One more session from this address this hour."""
        if not self.sessions_per_ip_per_hour:
            return True, 0.0
        with self._mutex:
            now = self._clock()
            _prune(self._ip_hits, now, 3600)
            hits = self._ip_hits.setdefault(client_ip, deque())
            if len(hits) >= self.sessions_per_ip_per_hour:
                return False, max(0.0, 3600 - (now - hits[0]))
            hits.append(now)
            return True, 0.0

    def take_turn(self) -> tuple[bool, float]:
        """One more agent turn today (UTC)."""
        if not self.daily_turn_cap:
            return True, 0.0
        with self._mutex:
            now = self._utc_now()
            if now.date() != self._turn_day:
                self._turn_day, self._turns_today = now.date(), 0
            if self._turns_today >= self.daily_turn_cap:
                midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
                return False, (midnight - now).total_seconds()
            self._turns_today += 1
            return True, 0.0
