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
import re
from functools import partial
from typing import Any

import anthropic
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.sse import KEEPALIVE_COMMENT, format_sse_event
from pydantic import BaseModel, Field

from app.agent import orchestrator
from app.agent.sessions import InMemorySessionStore, Session, SessionStore, to_jsonable, trim_history
from app.core.config import settings

router = APIRouter()

_store: SessionStore = InMemorySessionStore(
    settings.agent_session_ttl_s,
    settings.agent_rate_limit_per_minute,
    max_sessions=settings.agent_max_sessions,
    sessions_per_ip_per_hour=settings.agent_sessions_per_ip_per_hour,
    daily_turn_cap=settings.agent_daily_turn_cap,
)
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


OWN_KEY_HEADER = "X-Anthropic-Key"
OWN_KEY_PATTERN = re.compile(r"sk-ant-[A-Za-z0-9_-]{20,250}")


def own_key(header: str | None) -> str | None:
    """
    The user's own Anthropic key from the X-Anthropic-Key header, or None to use the server's key.

    Bring your own key: the key is used for this one turn and then dropped. It is never stored in the
    session, written to the database, logged or returned, and no error message repeats it.
    """
    if not header or not header.strip():
        return None
    key = header.strip()
    if not OWN_KEY_PATTERN.fullmatch(key):
        raise AgentError(400, "invalid_api_key", "That doesn't look like an Anthropic API key (it starts with sk-ant-)")
    return key


def classify(exc: BaseException, own: bool = False) -> AgentError:
    """Maps a failure while running the agent to a clean error. own: the turn ran on the user's key."""
    if isinstance(exc, AgentError):
        return exc
    if own:
        # the user's key is the likely cause; say so, without repeating the key
        if isinstance(exc, anthropic.AuthenticationError):
            return AgentError(401, "invalid_api_key", "Anthropic rejected your API key; check it and try again")
        if isinstance(exc, (anthropic.PermissionDeniedError, anthropic.NotFoundError)):
            return AgentError(403, "api_key_forbidden", f"Your Anthropic key can't use the model {settings.agent_model}")
        if isinstance(exc, anthropic.RateLimitError):
            return AgentError(429, "api_key_rate_limited", "Your Anthropic key is being rate limited; try again shortly")
        if isinstance(exc, anthropic.BadRequestError) and "credit balance" in str(exc).lower():
            return AgentError(402, "api_key_no_credit", "Your Anthropic account is out of credit")
    if isinstance(exc, TimeoutError):
        return AgentError(504, "agent_timeout", f"The agent did not finish within {settings.agent_timeout_s:g} s")
    if isinstance(exc, anthropic.RateLimitError):
        return AgentError(503, "model_rate_limited", "The model API is rate limiting requests; try again shortly")
    if isinstance(exc, anthropic.APIStatusError):
        return AgentError(502, "model_api_error", f"The model API returned {exc.status_code}")
    if isinstance(exc, anthropic.APIConnectionError):
        return AgentError(502, "model_api_unreachable", "Could not reach the model API")
    return AgentError(500, "agent_error", f"The agent failed: {type(exc).__name__}")


def admit(body: AgentMessageIn, store: SessionStore, own: bool = False) -> Session:
    """
    Checks the session, the rate limit, that no other turn is running and the daily cap. Raises AgentError.
    own: the turn runs on the user's own key, so it doesn't count toward the daily cap.
    """
    session = store.get(body.session_id)
    if session is None:
        raise AgentError(404, "unknown_session",
                         "Unknown or expired session; start a new one with POST /agent/sessions")
    allowed, retry_after = store.allow(session.id)
    if not allowed:
        raise AgentError(429, "rate_limited",
                         f"At most {settings.agent_rate_limit_per_minute} messages a minute per session",
                         headers={"Retry-After": str(max(1, round(retry_after)))})
    lock = store.lock(session.id)
    if not lock.acquire(blocking=False):
        raise AgentError(409, "session_busy", "This session is still answering the previous message")
    if own:
        return session
    # counted last, so a rejected message never uses up the day's turns
    allowed, retry_after = store.take_turn()
    if not allowed:
        lock.release()
        raise AgentError(429, "daily_limit_reached", "Demo limit reached, try again tomorrow",
                         headers={"Retry-After": str(max(1, round(retry_after)))})
    return session


def user_text(body: AgentMessageIn) -> str:
    if body.selected_route_id is None:
        return body.message
    return f"[App context: the user has selected route {body.selected_route_id} on the map.]\n{body.message}"


def _last_result(steps, tool: str):
    for step in reversed(steps):
        if step.tool == tool and step.error is None and isinstance(step.full_result, dict):
            yield step


def _stop_label(stop: dict) -> str:
    # "San Benito County, California, United States" -> "San Benito County"
    name = (stop.get("name") or "").split(",")[0]
    if stop.get("kind") == "lunch":
        return f"Lunch, day {stop.get('day')} · near {name}"
    if stop.get("kind") == "destination":
        return name
    return f"Night {stop.get('day')} · {name}"


def place_groups(steps, answer: dict) -> list[dict]:
    """
    This turn's find_places groups for the map and list, each labelled with the stop it belongs to,
    and each recommended place marked with the agent's reason. Ids the answer names that no group
    returned are dropped, so the app only highlights places the search actually found.
    """
    labels: dict[str, str] = {}
    for step in steps:
        if step.tool == "plan_stops" and step.error is None and isinstance(step.full_result, dict):
            for stop in (step.full_result.get("stops") or []) + (step.full_result.get("lunch_stops") or []):
                labels[str(stop.get("id"))] = _stop_label(stop)
    reasons = {str(p.get("id")): str(p.get("reason") or "") for p in answer.get("places") or [] if isinstance(p, dict)}

    groups = []
    for step in steps:
        if step.tool != "find_places" or step.error is not None or not isinstance(step.full_result, dict):
            continue
        for group in step.full_result.get("groups") or []:
            places = [{**place, "recommended": place["id"] in reasons, "reason": reasons.get(place["id"]) or None}
                      for place in group.get("places") or []]
            groups.append({**group, "label": labels.get(str(group.get("near")), str(group.get("near"))),
                           "places": places})
    return groups


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

    places = place_groups(turn.steps, answer)

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
        "places": places,
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
def create_session(request: Request, store: SessionStore = Depends(get_store)):
    # Behind a reverse proxy, run uvicorn with --proxy-headers so this is the visitor's address
    client_ip = request.client.host if request.client else "unknown"
    allowed, retry_after = store.allow_new_session(client_ip)
    if not allowed:
        return AgentError(429, "too_many_sessions",
                          f"At most {settings.agent_sessions_per_ip_per_hour} new conversations an hour; "
                          "try again later",
                          headers={"Retry-After": str(max(1, round(retry_after)))}).response()
    session = store.create()
    if session is None:
        return AgentError(503, "demo_busy", "The demo is busy right now; try again in a few minutes",
                          headers={"Retry-After": "300"}).response()
    return {"session_id": session.id, "expires_in_s": settings.agent_session_ttl_s}


@router.post("/message")
async def agent_message(
    body: AgentMessageIn,
    store: SessionStore = Depends(get_store),
    x_anthropic_key: str | None = Header(default=None, alias=OWN_KEY_HEADER),
):
    try:
        key = own_key(x_anthropic_key)
        session = admit(body, store, own=key is not None)
    except AgentError as e:
        return e.response()
    lock = store.lock(session.id)
    try:
        loop = asyncio.get_running_loop()
        work = partial(orchestrator.run_agent_turn, list(session.messages), user_text(body), api_key=key)
        turn = await asyncio.wait_for(loop.run_in_executor(None, work), timeout=settings.agent_timeout_s)
        return finish(store, session, turn)
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
        session = admit(body, store, own=key is not None)
    except AgentError as e:
        return e.response()
    own = key is not None

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

    def on_event(event: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, ("event", event))

    def work() -> None:
        try:
            turn = orchestrator.run_agent_turn(list(session.messages), user_text(body), on_event, api_key=key)
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
                    yield _sse("error", classify(payload, own=own).body())
                    return
        finally:
            lock.release()

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
