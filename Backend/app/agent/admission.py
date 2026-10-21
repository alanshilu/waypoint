"""Whether a message or a new conversation may go ahead: the session, the limits, and one turn at a time."""

from __future__ import annotations

from app.agent.errors import AgentError, retry_after
from app.agent.limits import AgentLimits
from app.agent.sessions import Session, SessionStore
from app.core.config import settings


def admit_message(session_id: str, store: SessionStore, limits: AgentLimits, own: bool = False) -> Session:
    """
    The session, once it exists, is within its rate limit, isn't answering another message (its lock is then
    held, and the caller releases it) and the day's turns aren't used up. Raises AgentError.
    own: the turn runs on the user's own key, so it doesn't count toward the daily cap.
    """
    session = store.get(session_id)
    if session is None:
        raise AgentError(404, "unknown_session", "Unknown or expired session; start a new one with POST /agent/sessions")
    allowed, wait = limits.allow_message(session.id)
    if not allowed:
        raise AgentError(429, "rate_limited", f"At most {settings.agent_rate_limit_per_minute} messages a minute per session",
                         headers=retry_after(wait))
    lock = store.lock(session.id)
    if not lock.acquire(blocking=False):
        raise AgentError(409, "session_busy", "This session is still answering the previous message")
    if own:
        return session
    # counted last, so a rejected message never uses up the day's turns
    allowed, wait = limits.take_turn()
    if not allowed:
        lock.release()
        raise AgentError(429, "daily_limit_reached", "Demo limit reached, try again tomorrow", headers=retry_after(wait))
    return session


def admit_new_session(client_ip: str, store: SessionStore, limits: AgentLimits) -> Session:
    """A new session for this address, within the per-address limit and the store's capacity. Raises AgentError."""
    allowed, wait = limits.allow_new_session(client_ip)
    if not allowed:
        raise AgentError(429, "too_many_sessions",
                         f"At most {settings.agent_sessions_per_ip_per_hour} new conversations an hour; try again later",
                         headers=retry_after(wait))
    session = store.create()
    if session is None:
        raise AgentError(503, "demo_busy", "The demo is busy right now; try again in a few minutes",
                         headers={"Retry-After": "300"})
    return session
