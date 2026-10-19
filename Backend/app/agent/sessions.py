"""
Conversation sessions for POST /agent/message.

Sessions live in memory (InMemorySessionStore): REDIS_URL is configured, but no
Redis server is reachable in this environment and the redis package is not
installed. SessionStore is the seam for a Redis-backed store later; everything
it stores is plain JSON so it can move without changes.

Consequences of the in-memory store: sessions are lost on restart, and with
several worker processes each worker has its own sessions. Run one worker, or
switch to a shared store, before scaling out.

The store also holds the public demo's cost limits: at most max_sessions live
sessions, at most sessions_per_ip_per_hour new sessions from one address, and
at most daily_turn_cap agent turns per UTC day across everyone. 0 turns a limit
off. Like the sessions, the counters are per process and reset on restart.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Session:
    id: str
    messages: list = field(default_factory=list)  # JSON-serialisable Messages API history
    trip_id: int | None = None
    updated_at: float = field(default_factory=time.monotonic)


class SessionStore(Protocol):
    def create(self) -> Session | None: ...
    def get(self, session_id: str) -> Session | None: ...
    def save(self, session: Session) -> None: ...
    def allow(self, session_id: str) -> tuple[bool, float]: ...
    def allow_new_session(self, client_ip: str) -> tuple[bool, float]: ...
    def take_turn(self) -> tuple[bool, float]: ...
    def lock(self, session_id: str) -> threading.Lock: ...


class InMemorySessionStore:
    """Sessions in a dict, expiring after ttl_s without use, with a per-session sliding-window rate limit."""

    def __init__(
        self,
        ttl_s: float,
        rate_per_minute: int,
        clock=time.monotonic,
        *,
        max_sessions: int = 0,
        sessions_per_ip_per_hour: int = 0,
        daily_turn_cap: int = 0,
        utc_now: Callable[[], datetime] = _utc_now,
    ):
        self.ttl_s = ttl_s
        self.rate_per_minute = rate_per_minute
        self.max_sessions = max_sessions
        self.sessions_per_ip_per_hour = sessions_per_ip_per_hour
        self.daily_turn_cap = daily_turn_cap
        self._clock = clock
        self._utc_now = utc_now
        self._sessions: dict[str, Session] = {}
        self._hits: dict[str, deque[float]] = {}
        self._ip_hits: dict[str, deque[float]] = {}
        self._turn_day = None
        self._turns_today = 0
        self._locks: dict[str, threading.Lock] = {}
        self._mutex = threading.Lock()

    def _expire(self, now: float) -> None:
        for sid in [sid for sid, s in self._sessions.items() if now - s.updated_at > self.ttl_s]:
            self._sessions.pop(sid, None)
            self._hits.pop(sid, None)
            self._locks.pop(sid, None)

    def create(self) -> Session | None:
        """A new session, or None when max_sessions are already live."""
        with self._mutex:
            now = self._clock()
            self._expire(now)
            if self.max_sessions and len(self._sessions) >= self.max_sessions:
                return None
            session = Session(id=secrets.token_urlsafe(16), updated_at=now)
            self._sessions[session.id] = session
            self._locks[session.id] = threading.Lock()
            return session

    def allow_new_session(self, client_ip: str) -> tuple[bool, float]:
        """(allowed, retry_after_s) for one more session from client_ip this hour. Counts it when allowed."""
        if not self.sessions_per_ip_per_hour:
            return True, 0.0
        with self._mutex:
            now = self._clock()
            for ip in list(self._ip_hits):  # forget addresses with nothing in the window
                hits = self._ip_hits[ip]
                while hits and now - hits[0] >= 3600:
                    hits.popleft()
                if not hits:
                    del self._ip_hits[ip]
            hits = self._ip_hits.setdefault(client_ip, deque())
            if len(hits) >= self.sessions_per_ip_per_hour:
                return False, max(0.0, 3600 - (now - hits[0]))
            hits.append(now)
            return True, 0.0

    def take_turn(self) -> tuple[bool, float]:
        """(allowed, retry_after_s) for one more agent turn today (UTC). Counts it when allowed."""
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

    def get(self, session_id: str) -> Session | None:
        with self._mutex:
            self._expire(self._clock())
            return self._sessions.get(session_id)

    def save(self, session: Session) -> None:
        with self._mutex:
            session.updated_at = self._clock()
            self._sessions[session.id] = session

    def allow(self, session_id: str) -> tuple[bool, float]:
        """(allowed, retry_after_s). Counts the request when allowed."""
        with self._mutex:
            now = self._clock()
            hits = self._hits.setdefault(session_id, deque())
            while hits and now - hits[0] >= 60:
                hits.popleft()
            if len(hits) >= self.rate_per_minute:
                return False, max(0.0, 60 - (now - hits[0]))
            hits.append(now)
            return True, 0.0

    def lock(self, session_id: str) -> threading.Lock:
        with self._mutex:
            return self._locks.setdefault(session_id, threading.Lock())


THINKING_TYPES = {"thinking", "redacted_thinking"}


def to_jsonable(messages: list) -> list[dict]:
    """History as plain JSON: SDK content blocks become dicts the API accepts back unchanged."""
    out = []
    for message in messages:
        content = message["content"]
        if isinstance(content, list):
            content = [
                block.model_dump(mode="json", exclude_none=True) if hasattr(block, "model_dump") else block
                for block in content
            ]
        out.append({"role": message["role"], "content": content})
    return out


def _is_user_text(message: dict) -> bool:
    """A turn the user typed, as opposed to a user message carrying tool results."""
    content = message["content"]
    return message["role"] == "user" and (
        isinstance(content, str) or not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
    )


def trim_history(messages: list[dict], max_turns: int) -> list[dict]:
    """
    Keeps the last max_turns user turns, cutting only at a typed user message so
    tool_use / tool_result pairs stay together.

    When anything is cut, thinking blocks are also removed from what remains.
    A Claude thinking block is signed against every message before it, so after
    the front of the history changes those blocks would fail validation. Without
    them the request stays valid; the model only loses its earlier reasoning.
    """
    starts = [i for i, m in enumerate(messages) if _is_user_text(m)]
    if len(starts) <= max_turns:
        return messages
    kept = messages[starts[-max_turns]:]
    trimmed = []
    for message in kept:
        content: Any = message["content"]
        if message["role"] == "assistant" and isinstance(content, list):
            content = [b for b in content if not (isinstance(b, dict) and b.get("type") in THINKING_TYPES)]
            if not content:
                continue
        trimmed.append({"role": message["role"], "content": content})
    return trimmed
