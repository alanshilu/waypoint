"""
Conversation sessions for POST /agent/message.

Sessions live in memory (InMemorySessionStore). SessionStore is the seam for a shared store (Redis, say)
later; everything a session holds is plain JSON so it can move without changes. With the in-memory store,
sessions are lost on restart, and with several worker processes each has its own: run one worker, or switch
to a shared store, before scaling out. Rate limits and the daily cap are a separate concern (limits.py).
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Session:
    id: str
    messages: list = field(default_factory=list)  # JSON-serialisable Messages API history
    trip_id: int | None = None
    updated_at: float = field(default_factory=time.monotonic)


class SessionStore(Protocol):
    def create(self) -> Session | None:
        """A new session, or None when the store is full."""
        ...

    def get(self, session_id: str) -> Session | None: ...
    def save(self, session: Session) -> None: ...

    def lock(self, session_id: str) -> threading.Lock:
        """Held while a turn runs, so a session answers one message at a time."""
        ...


class InMemorySessionStore:
    """Sessions in a dict, expiring after ttl_s without use; at most max_sessions live at once (0: no limit)."""

    def __init__(self, ttl_s: float, *, max_sessions: int = 0, clock: Callable[[], float] = time.monotonic):
        self.ttl_s = ttl_s
        self.max_sessions = max_sessions
        self._clock = clock
        self._sessions: dict[str, Session] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._mutex = threading.Lock()

    def _expire(self, now: float) -> None:
        for sid in [sid for sid, s in self._sessions.items() if now - s.updated_at > self.ttl_s]:
            self._sessions.pop(sid, None)
            self._locks.pop(sid, None)

    def create(self) -> Session | None:
        with self._mutex:
            now = self._clock()
            self._expire(now)
            if self.max_sessions and len(self._sessions) >= self.max_sessions:
                return None
            session = Session(id=secrets.token_urlsafe(16), updated_at=now)
            self._sessions[session.id] = session
            self._locks[session.id] = threading.Lock()
            return session

    def get(self, session_id: str) -> Session | None:
        with self._mutex:
            self._expire(self._clock())
            return self._sessions.get(session_id)

    def save(self, session: Session) -> None:
        with self._mutex:
            session.updated_at = self._clock()
            self._sessions[session.id] = session

    def lock(self, session_id: str) -> threading.Lock:
        with self._mutex:
            return self._locks.setdefault(session_id, threading.Lock())
