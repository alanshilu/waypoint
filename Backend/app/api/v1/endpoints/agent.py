"""
The trip agent over HTTP.

    POST /agent/sessions           start a conversation -> {session_id, expires_in_s}
    POST /agent/message            one turn, JSON response when it finishes
    POST /agent/message/stream     the same turn as server-sent events:
                                   start, tool_start / tool_end as they happen, then final (or error)

This module is only the HTTP side: the agent (orchestrator.Agent), the session store, the limits, admission
(admission.py), errors (errors.py) and the response shape (responses.py) live in app/agent and come in
as dependencies. Errors are always {"error": {"code", "message"}} with a matching status.
"""

from __future__ import annotations

import asyncio
import json
import logging
from functools import partial
from typing import Any, Protocol

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from fastapi.sse import KEEPALIVE_COMMENT, format_sse_event
from pydantic import BaseModel, Field

from app.agent.admission import admit_message, admit_new_session
from app.agent.errors import OWN_KEY_HEADER, AgentError, classify, own_key
from app.agent.history import to_jsonable, trim_history
from app.agent.limits import AgentLimits, InMemoryLimits
from app.agent.orchestrator import Agent, AgentTurn, get_agent
from app.agent.responses import build_response, user_text
from app.agent.sessions import InMemorySessionStore, Session, SessionStore
from app.core.config import settings
from app.core.db import SessionLocal
from app.services import sharing

router = APIRouter()
log = logging.getLogger(__name__)

KEEPALIVE_EVERY_S = 15

_store: SessionStore = InMemorySessionStore(settings.agent_session_ttl_s, max_sessions=settings.agent_max_sessions)
_limits: AgentLimits = InMemoryLimits(
    settings.agent_rate_limit_per_minute,
    sessions_per_ip_per_hour=settings.agent_sessions_per_ip_per_hour,
    daily_turn_cap=settings.agent_daily_turn_cap,
)


def get_store() -> SessionStore:
    """FastAPI dependency; tests override it with a store of their own."""
    return _store


def get_limits() -> AgentLimits:
    """FastAPI dependency; tests override it with limits of their own."""
    return _limits


class AgentMessageIn(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=4000)
    # The route the user picked in the app since the last message, so the agent knows about it
    selected_route_id: int | None = None


def finish(store: SessionStore, session: Session, turn: AgentTurn) -> dict[str, Any]:
    """The response for the app, after the session keeps the trip and the trimmed history."""
    response = build_response(session, turn)
    session.trip_id = response["trip_id"]
    session.messages = trim_history(to_jsonable(turn.messages), settings.agent_history_max_turns)
    store.save(session)
    return response


class PlanStore(Protocol):
    """Where a trip's latest plan is kept for its share link (trips.shared_plan)."""

    def save(self, trip_id: int, snapshot: dict) -> None: ...


class DbPlanStore:
    def save(self, trip_id: int, snapshot: dict) -> None:
        with SessionLocal() as db:
            sharing.save_plan(db, trip_id, snapshot)


_plans: PlanStore = DbPlanStore()


def get_plan_store() -> PlanStore:
    """FastAPI dependency; tests override it."""
    return _plans


def keep_plan(plans: PlanStore, response: dict[str, Any]) -> None:
    """Keeps the turn's planned stops and places for the trip's share link. A failure here never fails the turn."""
    snapshot = sharing.plan_snapshot(response)
    if response.get("trip_id") is None or snapshot is None:
        return
    try:
        plans.save(response["trip_id"], snapshot)
    except Exception:  # noqa: BLE001 - the reply still stands; the share link shows the previous plan
        log.exception("Could not keep the plan for trip %s", response["trip_id"])


@router.post("/sessions")
def create_session(request: Request, store: SessionStore = Depends(get_store), limits: AgentLimits = Depends(get_limits)):
    # Behind a reverse proxy, run uvicorn with --proxy-headers so this is the visitor's address
    client_ip = request.client.host if request.client else "unknown"
    try:
        session = admit_new_session(client_ip, store, limits)
    except AgentError as e:
        return e.response()
    return {"session_id": session.id, "expires_in_s": settings.agent_session_ttl_s}


@router.post("/message")
async def agent_message(
    body: AgentMessageIn,
    store: SessionStore = Depends(get_store),
    limits: AgentLimits = Depends(get_limits),
    agent: Agent = Depends(get_agent),
    plans: PlanStore = Depends(get_plan_store),
    x_anthropic_key: str | None = Header(default=None, alias=OWN_KEY_HEADER),
):
    try:
        key = own_key(x_anthropic_key)
        session = admit_message(body.session_id, store, limits, own=key is not None)
    except AgentError as e:
        return e.response()
    lock = store.lock(session.id)
    try:
        loop = asyncio.get_running_loop()
        work = partial(agent.run, list(session.messages), user_text(body.message, body.selected_route_id), api_key=key)
        turn = await asyncio.wait_for(loop.run_in_executor(None, work), timeout=settings.agent_timeout_s)
        response = finish(store, session, turn)
        await asyncio.to_thread(keep_plan, plans, response)
        return response
    except Exception as e:  # noqa: BLE001 - every failure becomes a clean JSON error
        return classify(e, own=key is not None).response()
    finally:
        lock.release()


def _sse(event: str, data: Any) -> bytes:
    return format_sse_event(event=event, data_str=json.dumps(data, default=str))


@router.post("/message/stream")
async def agent_message_stream(
    body: AgentMessageIn,
    store: SessionStore = Depends(get_store),
    limits: AgentLimits = Depends(get_limits),
    agent: Agent = Depends(get_agent),
    plans: PlanStore = Depends(get_plan_store),
    x_anthropic_key: str | None = Header(default=None, alias=OWN_KEY_HEADER),
):
    """
    Server-sent events. Session, rate-limit and busy errors come back as plain
    JSON before the stream starts; failures during the turn arrive as an
    'error' event. A comment line is sent every 15 s so proxies keep the
    connection open.
    """
    try:
        key = own_key(x_anthropic_key)
        session = admit_message(body.session_id, store, limits, own=key is not None)
    except AgentError as e:
        return e.response()
    own = key is not None

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

    def on_event(event: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, ("event", event))

    def work() -> None:
        try:
            turn = agent.run(list(session.messages), user_text(body.message, body.selected_route_id), on_event, api_key=key)
            loop.call_soon_threadsafe(queue.put_nowait, ("done", turn))
        except Exception as e:  # noqa: BLE001 - reported as an error event
            loop.call_soon_threadsafe(queue.put_nowait, ("error", e))

    async def events():
        lock = store.lock(session.id)
        try:
            loop.run_in_executor(None, work)
            deadline = loop.time() + settings.agent_timeout_s
            yield _sse("start", {"session_id": session.id})
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    yield _sse("error", classify(TimeoutError()).body())
                    return
                try:
                    kind, payload = await asyncio.wait_for(queue.get(), min(remaining, KEEPALIVE_EVERY_S))
                except TimeoutError:
                    yield KEEPALIVE_COMMENT
                    continue
                if kind == "event":
                    yield _sse(payload["type"], payload)
                elif kind == "done":
                    response = finish(store, session, payload)
                    await asyncio.to_thread(keep_plan, plans, response)
                    yield _sse("final", response)
                    return
                else:
                    yield _sse("error", classify(payload, own=own).body())
                    return
        finally:
            lock.release()

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
