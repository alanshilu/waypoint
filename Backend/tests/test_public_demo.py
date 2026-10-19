"""PUBLIC_DEMO: the trip list is off and trip/route writes are agent-only; local development is unchanged."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agent.tools import create_trip as create_trip_tool
from app.agent.tools import generate_route as generate_route_tool
from app.agent.tools import select_route as select_route_tool
from app.core.config import Settings, settings
from app.core.db import get_db
from app.core.internal import INTERNAL_HEADER
from app.main import app
from test_settings import REQUIRED

SECRET = "s3cret-for-tests"
TRIP_BODY = {"name": "x", "origin_name": "a", "origin_lat": 1, "origin_lon": 1,
             "destination_name": "b", "destination_lat": 2, "destination_lon": 2}


@pytest.fixture
def client():
    """A database that finds nothing, so a request that gets past the access rules ends in its own 404."""
    nothing = SimpleNamespace(filter=lambda *a: SimpleNamespace(first=lambda: None))
    app.dependency_overrides[get_db] = lambda: SimpleNamespace(query=lambda *a: nothing)
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def public_demo(monkeypatch):
    monkeypatch.setattr(settings, "public_demo", True)
    monkeypatch.setattr(settings, "internal_api_secret", SECRET)


def test_trip_list_is_gone(client, public_demo):
    r = client.get("/trips/trips")
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found"}


@pytest.mark.parametrize("method, path, body", [
    ("post", "/trips/", TRIP_BODY),
    ("post", "/routes/generate/1", None),
    ("post", "/routes/select/1", None),
])
@pytest.mark.parametrize("headers", [{}, {INTERNAL_HEADER: "wrong"}])
def test_writes_need_the_internal_secret(client, public_demo, method, path, body, headers):
    r = client.request(method, path, json=body, headers=headers)
    assert r.status_code == 403
    assert r.json()["detail"] == "This endpoint is not available in the public demo"


@pytest.mark.parametrize("path, missing", [("/routes/generate/1", "Trip not found"),
                                           ("/routes/select/1", "Route not found")])
def test_writes_with_the_secret_get_through(client, public_demo, path, missing):
    r = client.post(path, headers={INTERNAL_HEADER: SECRET})
    assert (r.status_code, r.json()["detail"]) == (404, missing)


def test_the_frontend_can_still_read_a_trip(client, public_demo):
    r = client.get("/trips/1")
    assert (r.status_code, r.json()["detail"]) == (404, "Trip not found")


def test_local_development_is_unchanged(client):
    assert settings.public_demo is False
    assert client.post("/routes/select/1").json()["detail"] == "Route not found"
    assert client.post("/routes/generate/1").json()["detail"] == "Trip not found"


def test_public_demo_without_a_secret_does_not_start(monkeypatch):
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("PUBLIC_DEMO", "true")
    monkeypatch.delenv("INTERNAL_API_SECRET", raising=False)
    with pytest.raises(ValidationError, match="INTERNAL_API_SECRET"):
        Settings(_env_file=None)


def test_agent_tools_send_the_secret(monkeypatch):
    monkeypatch.setattr(settings, "internal_api_secret", SECRET)
    sent = []

    def post(url, **kwargs):
        sent.append(kwargs.get("headers"))
        return SimpleNamespace(status_code=200, raise_for_status=lambda: None, json=lambda: {})

    for tool in (create_trip_tool, generate_route_tool, select_route_tool):
        monkeypatch.setattr(tool.requests, "post", post)
    create_trip_tool.create_trip("x", "a", 1, 1, "b", 2, 2)
    generate_route_tool.generate_routes(1)
    select_route_tool.select_route(1)
    assert sent == [{INTERNAL_HEADER: SECRET}] * 3
