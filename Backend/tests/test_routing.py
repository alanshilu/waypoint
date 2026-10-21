"""Route generation when OpenRouteService is slow or failing, with ORS stubbed."""

import time
from types import SimpleNamespace
from urllib import error

import pytest
from fastapi.testclient import TestClient
from geoalchemy2.shape import from_shape
from shapely.geometry import Point

from app.agent.tools import generate_route as generate_route_tool
from app.services.route_generation import RouteGenerator, get_route_generator
from app.core.db import get_db
from app.main import app
from app.services import routing_service
from app.services.routing_service import RoutingError


def fake_route(preference):
    return {"distance_miles": 1.0, "duration_seconds": 60, "duration_hms": "0h 1m", "ascent_m": 0,
            "descent_m": 0, "geometry": [], "extras": {}, "preference": preference}


def test_both_routes_are_requested_in_parallel(monkeypatch):
    def slow_route(*args, preference="fastest", avoid_features=None):
        time.sleep(0.4)
        return fake_route(preference)

    monkeypatch.setattr(routing_service, "get_single_route", slow_route)
    started = time.perf_counter()
    options = routing_service.get_route_options(0, 0, 1, 1)
    assert time.perf_counter() - started < 0.7  # one wait, not two
    assert options["fastest"]["preference"] == "fastest"
    assert options["backroads"]["preference"] == "shortest"


@pytest.mark.parametrize("raised, timed_out", [
    (TimeoutError("The read operation timed out"), True),
    (error.URLError(TimeoutError("timed out")), True),
    (error.URLError(ConnectionRefusedError("refused")), False),
    (error.HTTPError("https://ors", 503, "Service Unavailable", {}, None), False),
])
def test_ors_failures_become_routing_errors(monkeypatch, raised, timed_out):
    def failing_urlopen(*args, **kwargs):
        raise raised

    monkeypatch.setattr(routing_service.request, "urlopen", failing_urlopen)
    with pytest.raises(RoutingError) as caught:
        routing_service.get_single_route(0, 0, 1, 1)
    assert caught.value.timed_out is timed_out


@pytest.fixture
def client_with_trip():
    trip = SimpleNamespace(origin_point=from_shape(Point(-122.4, 37.8), srid=4326),
                           destination_point=from_shape(Point(-118.2, 34.1), srid=4326))
    query = SimpleNamespace(filter=lambda *a: SimpleNamespace(first=lambda: trip))
    app.dependency_overrides[get_db] = lambda: SimpleNamespace(query=lambda *a: query)
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.parametrize("timed_out, status", [(True, 504), (False, 502)])
def test_endpoint_reports_ors_failure_as_upstream_error(client_with_trip, timed_out, status):
    class FailingRouter:
        def get_route_options(self, *args):
            raise RoutingError("OpenRouteService did not answer within 90 s", timed_out=timed_out)

    app.dependency_overrides[get_route_generator] = lambda: RouteGenerator(FailingRouter())
    try:
        r = client_with_trip.post("/routes/generate/1")
    finally:
        app.dependency_overrides.pop(get_route_generator, None)
    assert r.status_code == status
    assert r.json()["detail"] == "OpenRouteService did not answer within 90 s"


def test_agent_tool_returns_the_reason_instead_of_raising(monkeypatch):
    response = SimpleNamespace(status_code=504, text="", json=lambda: {"detail": "OpenRouteService did not answer"})
    monkeypatch.setattr(generate_route_tool.requests, "post", lambda *a, **k: response)
    assert generate_route_tool.generate_routes(1) == {"error": "OpenRouteService did not answer"}
