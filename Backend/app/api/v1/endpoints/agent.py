"""
The trip agent over HTTP.

    POST /agent/sessions           start a conversation -> {session_id, expires_in_s}
    POST /agent/message            one turn, JSON response when it finishes
    POST /agent/message/stream     the same turn as server-sent events:
                                   start, tool_start / tool_end as they happen, then final (or error)

The agent logic is app.agent.orchestrator.run_agent_turn; this module only
manages sessions, limits and the response shape. Errors are always
{"error": {"code", "message"}} with a matching status.
"""

from __future__ import annotations

import asyncio
import json
from functools import partial
from typing import Any

import anthropic
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.sse import KEEPALIVE_COMMENT, format_sse_event
from pydantic import BaseModel, Field

from app.agent import orchestrator
from app.agent.sessions import InMemorySessionStore, Session, SessionStore, to_jsonable, trim_history
from app.core.config import settings

router = APIRouter()

_store: SessionStore = InMemorySessionStore(settings.agent_session_ttl_s, settings.agent_rate_limit_per_minute)
KEEPALIVE_EVERY_S = 15


def get_store() -> SessionStore:
    """FastAPI dependency; tests override it with a store of their own."""
    return _store


class AgentMessageIn(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=4000)
    # The route the user picked in the app since the last message, so the agent knows about it
    selected_route_id: int | None = None


class AgentError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.headers = status, code, message, headers or {}

    def body(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}

    def response(self) -> JSONResponse:
        return JSONResponse(status_code=self.status, content=self.body(), headers=self.headers)


def classify(exc: BaseException) -> AgentError:
    """Maps a failure while running the agent to a clean error."""
    if isinstance(exc, AgentError):
        return exc
    if isinstance(exc, TimeoutError):
        return AgentError(504, "agent_timeout", f"The agent did not finish within {settings.agent_timeout_s:g} s")
    if isinstance(exc, anthropic.RateLimitError):
        return AgentError(503, "model_rate_limited", "The model API is rate limiting requests; try again shortly")
    if isinstance(exc, anthropic.APIStatusError):
        return AgentError(502, "model_api_error", f"The model API returned {exc.status_code}")
    if isinstance(exc, anthropic.APIConnectionError):
        return AgentError(502, "model_api_unreachable", "Could not reach the model API")
    return AgentError(500, "agent_error", f"The agent failed: {type(exc).__name__}")


def admit(body: AgentMessageIn, store: SessionStore) -> Session:
    """Checks the session, the rate limit and that no other turn is running. Raises AgentError."""
    session = store.get(body.session_id)
    if session is None:
        raise AgentError(404, "unknown_session",
                         "Unknown or expired session; start a new one with POST /agent/sessions")
    allowed, retry_after = store.allow(session.id)
    if not allowed:
        raise AgentError(429, "rate_limited",
                         f"At most {settings.agent_rate_limit_per_minute} messages a minute per session",
                         headers={"Retry-After": str(max(1, round(retry_after)))})
    if not store.lock(session.id).acquire(blocking=False):
        raise AgentError(409, "session_busy", "This session is still answering the previous message")
    return session


def user_text(body: AgentMessageIn) -> str:
    if body.selected_route_id is None:
        return body.message
    return f"[App context: the user has selected route {body.selected_route_id} on the map.]\n{body.message}"


def _last_result(steps, tool: str):
    for step in reversed(steps):
        if step.tool == tool and step.error is None and isinstance(step.full_result, dict):
            yield step


def build_response(session: Session, turn: orchestrator.AgentTurn) -> dict[str, Any]:
    answer = turn.final_answer or {}

    trip_id = session.trip_id
    for tool in ("plan_stops", "generate_routes", "create_trip"):
        step = next(_last_result(turn.steps, tool), None)
        if step and step.full_result.get("trip_id") is not None:
            trip_id = step.full_result["trip_id"]
            break

    # The stops the answer names, resolved from this turn's plan_stops results
    known: dict[str, dict] = {}
    for step in turn.steps:
        if step.tool == "plan_stops" and step.error is None and isinstance(step.full_result, dict):
            for stop in step.full_result.get("stops") or []:
                known[str(stop.get("id"))] = stop
    planned_stops = [known[s] for s in answer.get("stops") or [] if s in known]

    poi_step = next(_last_result(turn.steps, "search_pois"), None)
    pois = None
    if poi_step:
        pois = {"center": {"lat": poi_step.args.get("lat"), "lon": poi_step.args.get("lon")},
                "items": poi_step.full_result.get("pois") or []}

    return {
        "session_id": session.id,
        "trip_id": trip_id,
        "reply": turn.reply,
        "answer": answer,
        "planned_stops": planned_stops,
        "pois": pois,
        "tool_calls": [
            {"tool": s.tool, "ms": s.ms, "cached": s.cached, "error": s.error, "tokens": s.tokens,
             "model_call": s.model_call}
            for s in turn.steps
        ],
        "usage": turn.usage.to_dict(),
    }


def finish(store: SessionStore, session: Session, turn: orchestrator.AgentTurn) -> dict[str, Any]:
    response = build_response(session, turn)
    session.trip_id = response["trip_id"]
    session.messages = trim_history(to_jsonable(turn.messages), settings.agent_history_max_turns)
    store.save(session)
    return response


@router.post("/sessions")
def create_session(store: SessionStore = Depends(get_store)):
    session = store.create()
    return {"session_id": session.id, "expires_in_s": settings.agent_session_ttl_s}


@router.post("/message")
async def agent_message(body: AgentMessageIn, store: SessionStore = Depends(get_store)):
    try:
        session = admit(body, store)
    except AgentError as e:
        return e.response()
    lock = store.lock(session.id)
    try:
        loop = asyncio.get_running_loop()
        work = partial(orchestrator.run_agent_turn, list(session.messages), user_text(body))
        turn = await asyncio.wait_for(loop.run_in_executor(None, work), timeout=settings.agent_timeout_s)
        return finish(store, session, turn)
    except Exception as e:  # noqa: BLE001 - every failure becomes a clean JSON error
        return classify(e).response()
    finally:
        lock.release()


def _sse(event: str, data: Any) -> bytes:
    return format_sse_event(event=event, data_str=json.dumps(data, default=str))


@router.post("/message/stream")
async def agent_message_stream(body: AgentMessageIn, store: SessionStore = Depends(get_store)):
    """
    Server-sent events. Session, rate-limit and busy errors come back as plain
    JSON before the stream starts; failures during the turn arrive as an
    'error' event. A comment line is sent every 15 s so proxies keep the
    connection open.
    """
    try:
        session = admit(body, store)
    except AgentError as e:
        return e.response()

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

    def on_event(event: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, ("event", event))

    def work() -> None:
        try:
            turn = orchestrator.run_agent_turn(list(session.messages), user_text(body), on_event)
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
                    yield _sse("final", finish(store, session, payload))
                    return
                else:
                    yield _sse("error", classify(payload).body())
                    return
        finally:
            lock.release()

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
