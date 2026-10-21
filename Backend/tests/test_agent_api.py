"""
POST /agent/message and /agent/message/stream with the Anthropic client faked.
No model, network or database is used: the agent is built with fake model clients
that return scripted responses, and with stub tools.
"""

import json
import threading
import time
from contextlib import contextmanager

import anthropic
import httpx
import pytest
from anthropic.types.beta import BetaMessage, BetaTextBlock, BetaThinkingBlock, BetaToolUseBlock, BetaUsage
from fastapi.testclient import TestClient

from app.agent.history import to_jsonable, trim_history
from app.agent.limits import InMemoryLimits
from app.agent.orchestrator import Agent, get_agent
from app.agent.sessions import InMemorySessionStore
from app.api.v1.endpoints import agent as agent_api
from app.core.config import settings
from app.main import app

FINAL = {
    "summary": "Take the fastest route.",
    "recommended_route_type": "fastest",
    "departure_window": {"start": "", "end": "", "reason": ""},
    "stops": ["17-1"],
    "warnings": [],
}


def usage(i=100, o=20):
    return BetaUsage.model_construct(input_tokens=i, output_tokens=o, cache_read_input_tokens=0,
                                     cache_creation_input_tokens=0)


def tool_call_response(*calls):
    blocks = [BetaThinkingBlock.model_construct(type="thinking", thinking="", signature="sig")]
    blocks += [BetaToolUseBlock.model_construct(type="tool_use", id=f"tu_{i}", name=name, input=args)
               for i, (name, args) in enumerate(calls)]
    return BetaMessage.model_construct(id="m1", type="message", role="assistant", model="test",
                                       content=blocks, stop_reason="tool_use", stop_details=None, usage=usage())


def final_response(answer=FINAL):
    return BetaMessage.model_construct(
        id="m2", type="message", role="assistant", model="test",
        content=[BetaTextBlock.model_construct(type="text", text=json.dumps(answer))],
        stop_reason="end_turn", stop_details=None, usage=usage(50, 30))


class FakeMessages:
    """Returns the queued responses in order; records the messages each call was sent."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(json.loads(json.dumps(to_jsonable(kwargs["messages"]))))
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return item()
        return item


def client_over(messages: FakeMessages):
    return type("C", (), {"beta": type("B", (), {"messages": messages})()})()


class FakeClients:
    """
    ModelClients for tests: the server's client answers from `server`; a client opened on a user's key
    answers from `own`, and records the key and that it was closed.
    """

    def __init__(self, server: FakeMessages, own: FakeMessages | None = None):
        self.server, self.own = server, own or FakeMessages([])
        self.keys: list[str] = []
        self.closed = 0

    @contextmanager
    def open(self, api_key):
        if api_key is None:
            yield client_over(self.server)
            return
        self.keys.append(api_key)
        try:
            yield client_over(self.own)
        finally:
            self.closed += 1


# The tools the test agent has; a test adds the stubs it needs (see the tools fixture)
TOOLS: dict = {}


@pytest.fixture(autouse=True)
def no_tools():
    TOOLS.clear()
    yield
    TOOLS.clear()


def use_agent(clients) -> None:
    """The endpoints get an agent on these clients, with TOOLS."""
    app.dependency_overrides[get_agent] = lambda: Agent(clients, TOOLS, [])


def install(monkeypatch, responses) -> FakeMessages:
    """An agent whose server client answers with these responses; returns them to inspect the calls."""
    fake = FakeMessages(responses)
    fake.clients = FakeClients(fake)
    use_agent(fake.clients)
    return fake


def use_store(store: InMemorySessionStore, limits: InMemoryLimits | None = None) -> None:
    app.dependency_overrides[agent_api.get_store] = lambda: store
    app.dependency_overrides[agent_api.get_limits] = lambda: limits or InMemoryLimits(10)


@pytest.fixture
def store():
    s = InMemorySessionStore(ttl_s=3600)
    use_store(s)
    yield s
    app.dependency_overrides.clear()


@pytest.fixture
def tools():
    calls = []

    def create_trip(**args):
        calls.append(("create_trip", args))
        return {"trip_id": 9, "reused": False}

    def plan_stops(**args):
        calls.append(("plan_stops", args))
        return {"trip_id": 9, "stops": [{"id": "17-1", "day": 1, "kind": "destination", "name": "Los Angeles",
                                         "lat": 34.05, "lon": -118.24, "arrival_date": "2026-10-18"}]}

    TOOLS.update(create_trip=create_trip, plan_stops=plan_stops)
    return calls


@pytest.fixture
def client():
    return TestClient(app)


def new_session(client) -> str:
    r = client.post("/agent/sessions")
    assert r.status_code == 200
    return r.json()["session_id"]


def test_happy_path_returns_answer_trip_and_tool_calls(client, store, tools, monkeypatch):
    fake = install(monkeypatch, [
        tool_call_response(("create_trip", {"name": "x"}), ("plan_stops", {"trip_id": 9, "route_id": 17})),
        final_response(),
        final_response({**FINAL, "summary": "Still the fastest route."}),
    ])
    sid = new_session(client)

    r = client.post("/agent/message", json={"session_id": sid, "message": "SF to LA"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"] == FINAL
    assert body["reply"].startswith("Take the fastest route.")
    assert body["trip_id"] == 9
    assert [c["tool"] for c in body["tool_calls"]] == ["create_trip", "plan_stops"]
    assert body["tool_calls"][0]["tokens"] == {"input": 100, "output": 20, "cache_read": 0, "cache_write": 0}
    assert all(c["ms"] >= 0 and c["error"] is None for c in body["tool_calls"])
    assert body["planned_stops"][0]["name"] == "Los Angeles"
    assert body["usage"]["input_tokens"] == 150 and body["usage"]["requests"] == 2

    # The second message is sent with the first turn's history, and the session keeps the trip
    r2 = client.post("/agent/message", json={"session_id": sid, "message": "and again?", "selected_route_id": 17})
    assert r2.status_code == 200, r2.text
    assert r2.json()["trip_id"] == 9
    sent = fake.calls[-1]
    assert sent[0] == {"role": "user", "content": "SF to LA"}
    assert sent[-1]["content"].startswith("[App context: the user has selected route 17")
    assert len(sent) == 5  # user, assistant(tool_use), user(tool_results), assistant(final), user


def test_unknown_session_is_a_clean_404(client, store):
    r = client.post("/agent/message", json={"session_id": "nope", "message": "hi"})
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "unknown_session",
                                  "message": "Unknown or expired session; start a new one with POST /agent/sessions"}}
    assert client.post("/agent/message/stream", json={"session_id": "nope", "message": "hi"}).status_code == 404


def test_invalid_body_uses_the_same_error_shape(client, store):
    r = client.post("/agent/message", json={"session_id": "x", "message": ""})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_request"
    # other endpoints keep FastAPI's default 422 shape
    assert "detail" in client.get("/weather/forecast").json()


def test_rate_limit_per_session(client, monkeypatch):
    use_store(InMemorySessionStore(ttl_s=3600), InMemoryLimits(rate_per_minute=2))
    try:
        install(monkeypatch, [final_response(), final_response(), final_response()])
        sid, other = new_session(client), new_session(client)
        assert client.post("/agent/message", json={"session_id": sid, "message": "1"}).status_code == 200
        assert client.post("/agent/message", json={"session_id": sid, "message": "2"}).status_code == 200
        r = client.post("/agent/message", json={"session_id": sid, "message": "3"})
        assert r.status_code == 429
        assert r.json()["error"]["code"] == "rate_limited"
        assert int(r.headers["Retry-After"]) >= 1
        # the limit is per session
        assert client.post("/agent/message", json={"session_id": other, "message": "1"}).status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_rate_limit_window_slides():
    now = [0.0]
    limits = InMemoryLimits(rate_per_minute=2, clock=lambda: now[0])
    assert limits.allow_message("a")[0] and limits.allow_message("a")[0]
    allowed, retry = limits.allow_message("a")
    assert not allowed and retry == 60
    now[0] = 60.5
    assert limits.allow_message("a")[0]


@pytest.mark.parametrize("failure, status, code", [
    (anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com")), 502,
     "model_api_unreachable"),
    (RuntimeError("boom"), 500, "agent_error"),
])
def test_agent_error_is_clean_and_session_survives(client, store, monkeypatch, failure, status, code):
    install(monkeypatch, [failure, final_response()])
    sid = new_session(client)
    r = client.post("/agent/message", json={"session_id": sid, "message": "hi"})
    assert r.status_code == status
    assert r.json()["error"]["code"] == code
    assert "boom" not in r.text  # internals are not leaked
    # the failed turn is not saved and the session lock was released
    r2 = client.post("/agent/message", json={"session_id": sid, "message": "hi again"})
    assert r2.status_code == 200
    assert store.get(sid).messages[0] == {"role": "user", "content": "hi again"}


def test_timeout(client, store, monkeypatch):
    monkeypatch.setattr(settings, "agent_timeout_s", 0.2)
    install(monkeypatch, [lambda: (time.sleep(1), final_response())[1]])
    sid = new_session(client)
    r = client.post("/agent/message", json={"session_id": sid, "message": "hi"})
    assert r.status_code == 504
    assert r.json()["error"]["code"] == "agent_timeout"


def test_concurrent_turn_on_one_session_is_rejected(client, store, monkeypatch):
    sid = new_session(client)
    store.lock(sid).acquire()
    try:
        r = client.post("/agent/message", json={"session_id": sid, "message": "hi"})
        assert r.status_code == 409 and r.json()["error"]["code"] == "session_busy"
    finally:
        store.lock(sid).release()


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for frame in text.split("\n\n"):
        lines = [line for line in frame.splitlines() if line and not line.startswith(":")]
        if not lines:
            continue
        event = next(line[7:] for line in lines if line.startswith("event: "))
        data = json.loads("\n".join(line[6:] for line in lines if line.startswith("data: ")))
        events.append((event, data))
    return events


def test_stream_emits_tool_events_then_final(client, store, tools, monkeypatch):
    install(monkeypatch, [tool_call_response(("create_trip", {"name": "x"})), final_response()])
    sid = new_session(client)
    with client.stream("POST", "/agent/message/stream", json={"session_id": sid, "message": "SF to LA"}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        events = parse_sse(r.read().decode())
    assert [e for e, _ in events] == ["start", "tool_start", "tool_end", "final"]
    assert events[1][1]["tool"] == "create_trip"
    assert events[2][1]["tokens"]["output"] == 20
    assert events[-1][1]["trip_id"] == 9 and events[-1][1]["answer"] == FINAL
    assert store.get(sid).trip_id == 9


def test_stream_reports_agent_errors_as_an_event(client, store, monkeypatch):
    install(monkeypatch, [RuntimeError("boom")])
    sid = new_session(client)
    with client.stream("POST", "/agent/message/stream", json={"session_id": sid, "message": "hi"}) as r:
        events = parse_sse(r.read().decode())
    assert events[-1] == ("error", {"error": {"code": "agent_error", "message": "The agent failed: RuntimeError"}})
    assert store.lock(sid).acquire(blocking=False)  # released after the stream ended


def test_trim_history_cuts_at_user_turns_and_strips_thinking():
    def turn(n):
        return [
            {"role": "user", "content": f"q{n}"},
            {"role": "assistant", "content": [{"type": "thinking", "thinking": "", "signature": "s"},
                                              {"type": "tool_use", "id": f"t{n}", "name": "x", "input": {}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{n}", "content": "{}"}]},
            {"role": "assistant", "content": [{"type": "text", "text": f"a{n}"}]},
        ]

    history = turn(1) + turn(2) + turn(3)
    assert trim_history(history, 3) is history  # under the cap: untouched, thinking kept
    trimmed = trim_history(history, 2)
    assert trimmed[0] == {"role": "user", "content": "q2"}
    assert len(trimmed) == 8
    assert all(b.get("type") != "thinking" for m in trimmed if m["role"] == "assistant" for b in m["content"])
    # tool_use / tool_result pairs survive
    assert trimmed[1]["content"][0]["type"] == "tool_use" and trimmed[2]["content"][0]["type"] == "tool_result"


def test_sessions_expire():
    now = [0.0]
    s = InMemorySessionStore(ttl_s=10, clock=lambda: now[0])
    sid = s.create().id
    now[0] = 5
    assert s.get(sid) is not None
    now[0] = 16
    assert s.get(sid) is None


def test_a_rate_limit_of_zero_is_off_like_the_other_limits():
    limits = InMemoryLimits(rate_per_minute=0)
    assert all(limits.allow_message("a")[0] for _ in range(100))


def test_limits_forget_sessions_with_nothing_in_the_window():
    now = [0.0]
    limits = InMemoryLimits(rate_per_minute=2, clock=lambda: now[0])
    for sid in ("a", "b", "c"):
        limits.allow_message(sid)
    now[0] = 61
    limits.allow_message("d")
    assert set(limits._message_hits) == {"d"}  # noqa: SLF001 - expired sessions' windows don't pile up


def test_limits_are_thread_safe_under_parallel_rate_checks():
    limits = InMemoryLimits(rate_per_minute=50)
    results = []
    threads = [threading.Thread(target=lambda: results.append(limits.allow_message("a")[0])) for _ in range(200)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 50
