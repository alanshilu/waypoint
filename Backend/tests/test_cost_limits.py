"""The public demo's cost limits: sessions per IP, the daily turn cap, the session TTL and the live-session cap."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.agent.limits import InMemoryLimits
from app.agent.sessions import InMemorySessionStore
from app.api.v1.endpoints import agent as agent_api
from app.core.config import Settings
from app.main import app
from test_agent_api import final_response, install
from test_settings import REQUIRED


@pytest.fixture
def serve():
    """Serves the given store and limits to the API for one test."""

    def use(store=None, limits=None):
        store = store or InMemorySessionStore(3600)
        app.dependency_overrides[agent_api.get_store] = lambda: store
        app.dependency_overrides[agent_api.get_limits] = lambda: limits or InMemoryLimits(10)
        return TestClient(app)

    yield use
    app.dependency_overrides.clear()


# (a) new sessions per IP

def test_sessions_per_ip_are_limited_per_hour(serve):
    client = serve(limits=InMemoryLimits(10, sessions_per_ip_per_hour=2))
    assert client.post("/agent/sessions").status_code == 200
    assert client.post("/agent/sessions").status_code == 200
    r = client.post("/agent/sessions")
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "too_many_sessions"
    assert 1 <= int(r.headers["Retry-After"]) <= 3600


def test_ip_limit_is_per_address_and_the_window_slides():
    now = [0.0]
    limits = InMemoryLimits(10, clock=lambda: now[0], sessions_per_ip_per_hour=1)
    assert limits.allow_new_session("203.0.113.1") == (True, 0.0)
    assert limits.allow_new_session("203.0.113.1")[0] is False
    assert limits.allow_new_session("203.0.113.2")[0] is True
    now[0] = 3600
    assert limits.allow_new_session("203.0.113.1")[0] is True


# (b) daily turn cap

def test_daily_turn_cap_returns_a_clean_429_until_midnight_utc(serve, monkeypatch):
    today = [datetime(2026, 10, 19, 22, 0, tzinfo=timezone.utc)]
    client = serve(limits=InMemoryLimits(10, daily_turn_cap=2, utc_now=lambda: today[0]))
    install(monkeypatch, [final_response(), final_response(), final_response()])
    sid = client.post("/agent/sessions").json()["session_id"]
    assert client.post("/agent/message", json={"session_id": sid, "message": "1"}).status_code == 200
    assert client.post("/agent/message", json={"session_id": sid, "message": "2"}).status_code == 200

    for path in ("/agent/message", "/agent/message/stream"):
        r = client.post(path, json={"session_id": sid, "message": "3"})
        assert r.status_code == 429
        assert r.json() == {"error": {"code": "daily_limit_reached",
                                      "message": "Demo limit reached, try again tomorrow"}}
        assert r.headers["Retry-After"] == "7200"  # two hours to midnight UTC

    # a new UTC day starts a new count, and the session still works
    today[0] = datetime(2026, 10, 20, 0, 1, tzinfo=timezone.utc)
    assert client.post("/agent/message", json={"session_id": sid, "message": "4"}).status_code == 200


def test_rejected_messages_do_not_use_up_the_cap(serve, monkeypatch):
    store = InMemorySessionStore(3600)
    client = serve(store, InMemoryLimits(10, daily_turn_cap=1))
    install(monkeypatch, [final_response()])
    assert client.post("/agent/message", json={"session_id": "nope", "message": "1"}).status_code == 404
    sid = client.post("/agent/sessions").json()["session_id"]
    store.lock(sid).acquire()  # a turn already running on this session
    assert client.post("/agent/message", json={"session_id": sid, "message": "1"}).status_code == 409
    store.lock(sid).release()
    assert client.post("/agent/message", json={"session_id": sid, "message": "1"}).status_code == 200


# (c) session TTL and live-session cap

def test_live_sessions_are_capped_until_one_expires(serve):
    now = [0.0]
    client = serve(InMemorySessionStore(ttl_s=1800, clock=lambda: now[0], max_sessions=2))
    assert client.post("/agent/sessions").status_code == 200
    assert client.post("/agent/sessions").status_code == 200
    r = client.post("/agent/sessions")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "demo_busy"
    now[0] = 1801  # both sessions idle past the TTL
    assert client.post("/agent/sessions").status_code == 200


def test_demo_defaults(monkeypatch):
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    for name in ("AGENT_SESSION_TTL_S", "AGENT_MAX_SESSIONS", "AGENT_SESSIONS_PER_IP_PER_HOUR",
                 "AGENT_DAILY_TURN_CAP"):
        monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=None)
    assert (s.agent_session_ttl_s, s.agent_max_sessions, s.agent_sessions_per_ip_per_hour,
            s.agent_daily_turn_cap) == (1800, 200, 5, 200)
