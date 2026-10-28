"""
The agent turn's deadline (AGENT_TIMEOUT_S from when the turn started), so slow calls and retries stop in time.

The agent sets it for the turn (Agent.run); its tools send it with each request to this API as the
X-Waypoint-Deadline header (seconds since the epoch); DeadlineMiddleware reads it back for the request, where
ors_http.open_json keeps its retries inside it. A request without the header has no deadline. A client can
only shorten its own request with it: the budgets set by the services still apply.
"""

from __future__ import annotations

import math
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

DEADLINE_HEADER = "X-Waypoint-Deadline"

_deadline: ContextVar[float | None] = ContextVar("waypoint_deadline", default=None)


def remaining_s() -> float | None:
    """Seconds left before the deadline (0 when past it), or None when there is none."""
    at = _deadline.get()
    return None if at is None else max(0.0, at - time.time())


@contextmanager
def until(at: float | None) -> Iterator[None]:
    """The deadline (seconds since the epoch) for everything run inside the block; None for none."""
    token = _deadline.set(at)
    try:
        yield
    finally:
        _deadline.reset(token)


def headers() -> dict[str, str]:
    """The header that passes the current deadline on to this API; empty when there is none."""
    at = _deadline.get()
    return {} if at is None else {DEADLINE_HEADER: f"{at:.3f}"}


def parse(value: str | None) -> float | None:
    try:
        at = float(value) if value else None
    except ValueError:
        return None
    return at if at is not None and math.isfinite(at) else None


class DeadlineMiddleware:
    """Sets the request's deadline from its X-Waypoint-Deadline header (plain ASGI, so it reaches the endpoint)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        raw = dict(scope.get("headers") or []).get(DEADLINE_HEADER.lower().encode())
        with until(parse(raw.decode("latin-1") if raw else None)):
            await self.app(scope, receive, send)
