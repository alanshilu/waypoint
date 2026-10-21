"""
Bring your own key: a user's Anthropic key in X-Anthropic-Key runs that turn, skips the daily cap,
and is never stored, returned or logged.
"""

import json
import logging

import anthropic
import httpx2
import pytest
from fastapi.testclient import TestClient

from app.agent.limits import InMemoryLimits
from app.agent.orchestrator import Agent, AnthropicClients, get_agent
from app.agent.sessions import InMemorySessionStore
from app.main import app
from test_agent_api import TOOLS, FakeClients, FakeMessages, final_response, install, tool_call_response, use_store

KEY = "sk-ant-api03-" + "x7Q" * 20  # shaped like a real key, never valid


@pytest.fixture(autouse=True)
def no_tools():
    TOOLS.clear()
    yield
    TOOLS.clear()


@pytest.fixture
def store():
    s = InMemorySessionStore(3600)
    use_store(s, InMemoryLimits(10, daily_turn_cap=1))
    yield s
    app.dependency_overrides.clear()


@pytest.fixture
def client(store):
    return TestClient(app)


def own_client(monkeypatch, responses):
    """Turns on a user's key answer with these responses. Returns the clients, which record the keys and closes."""
    clients = app.dependency_overrides[get_agent]().clients  # the fake clients install() set up
    clients.own = FakeMessages(responses)
    return clients


def session(client) -> str:
    return client.post("/agent/sessions").json()["session_id"]


def test_the_turn_runs_on_the_users_key_not_the_servers(client, monkeypatch):
    install(monkeypatch, [])  # the server's client: any call to it fails the test
    made = own_client(monkeypatch, [final_response()])
    r = client.post("/agent/message", json={"session_id": session(client), "message": "hi"},
                    headers={"X-Anthropic-Key": KEY})
    assert r.status_code == 200
    assert (made.keys, made.closed) == ([KEY], 1)


def test_own_key_turns_do_not_count_toward_the_daily_cap(client, monkeypatch):
    install(monkeypatch, [final_response()])
    own_client(monkeypatch, [final_response(), final_response()])
    sid = session(client)
    assert client.post("/agent/message", json={"session_id": sid, "message": "1"}).status_code == 200
    assert client.post("/agent/message", json={"session_id": sid, "message": "2"}).status_code == 429
    for message in ("3", "4"):  # the demo's cap is used up; the user's own key still works
        r = client.post("/agent/message", json={"session_id": sid, "message": message},
                        headers={"X-Anthropic-Key": KEY})
        assert r.status_code == 200


@pytest.mark.parametrize("bad", ["not-a-key", "sk-ant-short", "sk-ant-" + "a" * 30 + " injected", "sk-proj-" + "a" * 40])
def test_a_malformed_key_is_rejected_before_anything_runs(client, monkeypatch, bad):
    install(monkeypatch, [])
    made = own_client(monkeypatch, [])
    for path in ("/agent/message", "/agent/message/stream"):
        r = client.post(path, json={"session_id": session(client), "message": "hi"}, headers={"X-Anthropic-Key": bad})
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "invalid_api_key"
        assert bad not in r.text
    assert made.keys == []


def test_the_key_is_not_kept_in_the_session_or_returned(client, store, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    install(monkeypatch, [])
    TOOLS["geocode_location"] = lambda **a: {"lat": 1, "lon": 2}
    own_client(monkeypatch, [tool_call_response(("geocode_location", {"query": "Austin"})), final_response()])
    sid = session(client)
    r = client.post("/agent/message", json={"session_id": sid, "message": "Austin"}, headers={"X-Anthropic-Key": KEY})
    assert r.status_code == 200
    assert KEY not in r.text
    assert KEY not in json.dumps(store.get(sid).messages)
    assert KEY not in caplog.text


def sdk_rejecting_the_key(monkeypatch, seen_keys):
    """The real Anthropic SDK, talking to a fake API that answers 401 like an invalid key does."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_keys.append(request.headers.get("x-api-key"))
        return httpx2.Response(401, json={"type": "error", "error": {
            "type": "authentication_error", "message": "invalid x-api-key"}})

    def make_client(api_key):
        return anthropic.Anthropic(api_key=api_key, max_retries=0,
                                   http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))

    app.dependency_overrides[get_agent] = lambda: Agent(AnthropicClients(None, make_client=make_client), TOOLS, [])


def test_a_rejected_key_is_a_clean_401_that_never_repeats_the_key(client, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)  # includes the SDK's and httpx's own request logging
    install(monkeypatch, [])
    seen = []
    sdk_rejecting_the_key(monkeypatch, seen)

    r = client.post("/agent/message", json={"session_id": session(client), "message": "hi"},
                    headers={"X-Anthropic-Key": KEY})
    assert r.status_code == 401
    assert r.json() == {"error": {"code": "invalid_api_key",
                                  "message": "Anthropic rejected your API key; check it and try again"}}

    stream = client.post("/agent/message/stream", json={"session_id": session(client), "message": "hi"},
                         headers={"X-Anthropic-Key": KEY})
    assert "event: error" in stream.text and "invalid_api_key" in stream.text

    assert seen == [KEY, KEY]  # the key did reach the API, as x-api-key
    for text in (r.text, stream.text, caplog.text):
        assert KEY not in text


def test_without_a_key_the_server_key_is_used_as_before(client, monkeypatch):
    install(monkeypatch, [final_response()])
    made = own_client(monkeypatch, [])
    r = client.post("/agent/message", json={"session_id": session(client), "message": "hi"},
                    headers={"X-Anthropic-Key": "  "})
    assert r.status_code == 200
    assert made.keys == []


def test_anthropic_clients_make_the_server_client_once_and_close_each_own_key_client():
    made, closed = [], []

    class Client:
        def __init__(self, api_key):
            self.api_key = api_key
            made.append(api_key)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            closed.append(self.api_key)

    clients = AnthropicClients("server-key", make_client=Client)
    assert made == []  # nothing is made until a turn needs it
    for _ in range(2):
        with clients.open(None) as c:
            assert c.api_key == "server-key"
    with clients.open(KEY) as c:
        assert c.api_key == KEY
    assert made == ["server-key", KEY] and closed == [KEY]  # the server client is reused, the user's is closed


def test_an_unknown_tool_is_reported_to_the_model_not_raised(monkeypatch):
    fake = FakeMessages([tool_call_response(("no_such_tool", {})), final_response()])
    turn = Agent(FakeClients(fake), {"geocode_location": lambda **a: {}}, []).run([], "hi")
    assert turn.steps[0].error == "Unknown tool 'no_such_tool'; available: geocode_location"
    tool_result = fake.calls[1][-1]["content"][0]
    assert tool_result["is_error"] is True and "Unknown tool" in tool_result["content"]
