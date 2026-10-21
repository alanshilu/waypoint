"""Turn-by-turn directions: parsed from OpenRouteService, stored with the route, kept out of the model's view."""

import io
import json
from types import SimpleNamespace

from geoalchemy2.shape import from_shape
from shapely.geometry import LineString

from app.agent.orchestrator import model_view
from app.api.v1.serializers import route_to_dict
from app.services import routing_service
from app.services.db_route_service import save_routes_to_db

COORDS = [[-122.4194, 37.77491, 16.0], [-122.41, 37.78, 20.0], [-122.40, 37.79, 25.0], [-121.88631, 37.33821, 30.0]]
SEGMENT = {
    "distance": 1000.0, "duration": 600.0, "ascent": 10, "descent": 5,
    "steps": [
        {"distance": 248.1, "duration": 32.4, "type": 11, "instruction": "Head northeast on Market Street",
         "name": "Market Street", "way_points": [0, 1]},
        {"distance": 49777.7, "duration": 1960.8, "type": 12, "instruction": "Keep left", "name": "-",
         "way_points": [1, 3]},
        {"distance": 0.0, "duration": 0.0, "type": 10, "instruction": "Arrive at East Santa Clara Street",
         "name": "-", "way_points": [3, 3]},
    ],
}


def test_steps_take_their_ends_from_the_full_geometry():
    steps = routing_service.directions_from(SEGMENT, COORDS)
    assert steps[0] == {"instruction": "Head northeast on Market Street", "name": "Market Street", "type": 11,
                        "distance_miles": 0.15, "duration_seconds": 32,
                        "start": [-122.4194, 37.77491], "end": [-122.41, 37.78]}
    keep_left = steps[1]
    assert keep_left["name"] is None  # ORS's "-" for an unnamed road
    assert (keep_left["distance_miles"], keep_left["end"]) == (30.93, [-121.88631, 37.33821])
    assert steps[2]["start"] == steps[2]["end"] and steps[2]["type"] == 10


def test_a_segment_without_steps_has_no_directions():
    assert routing_service.directions_from({"distance": 1.0}, COORDS) == []


def test_get_single_route_asks_for_instructions_and_returns_them(monkeypatch):
    sent = {}

    def urlopen(req, timeout):
        sent.update(json.loads(req.data))
        body = {"features": [{"geometry": {"coordinates": COORDS},
                              "properties": {"segments": [SEGMENT], "extras": {}}}]}
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setattr(routing_service.request, "urlopen", urlopen)
    route = routing_service.get_single_route(-122.4, 37.8, -121.9, 37.3)
    assert sent["instructions"] is True
    assert [s["type"] for s in route["directions"]] == [11, 12, 10]


def test_directions_are_saved_and_served():
    added = []
    db = SimpleNamespace(add=added.append, commit=lambda: None, refresh=lambda r: None)
    steps = routing_service.directions_from(SEGMENT, COORDS)
    data = {"distance_miles": 31.1, "duration_seconds": 1993, "ascent_m": 10, "descent_m": 5, "scenic_score": 1.0,
            "geometry": COORDS, "directions": steps}
    [saved] = save_routes_to_db(db, 7, {"fastest": data})
    assert saved.directions == steps

    saved.id, saved.geometry, saved.is_selected, saved.created_at = 1, from_shape(LineString([c[:2] for c in COORDS])), False, None
    assert route_to_dict(saved)["directions"] == steps


def test_routes_saved_before_directions_serve_null():
    route = SimpleNamespace(id=1, trip_id=7, route_type="fastest", distance_miles=31.1, duration_seconds=1993,
                            ascent_m=None, descent_m=None, scenic_score=1.0, is_selected=False,
                            geometry=from_shape(LineString([c[:2] for c in COORDS])), elevation_profile=None,
                            directions=None, created_at=None)
    assert route_to_dict(route)["directions"] is None


def test_the_model_sees_how_many_steps_not_the_steps():
    steps = routing_service.directions_from(SEGMENT, COORDS)
    result = {"routes": [{"id": 1, "route_type": "fastest", "directions": steps}]}
    assert model_view(result) == {"routes": [{"id": 1, "route_type": "fastest", "directions": {"steps": 3}}]}


# ---- Reusing a trip's routes ----

def generate_with(monkeypatch, saved_directions):
    """POST /routes/generate?reuse_existing=true for a trip whose two saved routes have these directions."""
    from fastapi.testclient import TestClient
    from shapely.geometry import Point

    from app.core.db import get_db
    from app.main import app
    from app.models.route import Route
    from app.models.trip import Trip
    from app.services.route_generation import RouteGenerator, get_route_generator

    trip = SimpleNamespace(origin_point=from_shape(Point(-122.4, 37.8), srid=4326),
                           destination_point=from_shape(Point(-118.2, 34.1), srid=4326))

    def route(id_, route_type, duration, directions):
        return SimpleNamespace(id=id_, trip_id=1, route_type=route_type, distance_miles=10.0, duration_seconds=duration,
                               ascent_m=0, descent_m=0, scenic_score=1.0, is_selected=False,
                               geometry=from_shape(LineString([c[:2] for c in COORDS])), elevation_profile=None,
                               directions=directions, created_at=None)

    saved = [route(2, "backroads", 200, saved_directions), route(1, "fastest", 100, saved_directions)]

    def query(model):
        if model is Trip:
            return SimpleNamespace(filter=lambda *a: SimpleNamespace(first=lambda: trip))
        assert model is Route
        return SimpleNamespace(filter=lambda *a: SimpleNamespace(order_by=lambda *a: saved))

    generated = []

    class Router:
        def get_route_options(self, *coords):
            generated.append(coords)
            return {}

    def save(db, trip_id, routes):
        return [route(3, "fastest", 100, []), route(4, "backroads", 200, [])]

    app.dependency_overrides[get_db] = lambda: SimpleNamespace(query=query)
    app.dependency_overrides[get_route_generator] = lambda: RouteGenerator(Router(), save=save)
    try:
        body = TestClient(app).post("/routes/generate/1?reuse_existing=true").json()
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_route_generator, None)
    return body, generated


def test_routes_with_directions_are_reused(monkeypatch):
    body, generated = generate_with(monkeypatch, saved_directions=[{"type": 11}])
    assert body["reused"] is True and generated == []
    assert [r["id"] for r in body["routes"]] == [1, 2]


def test_routes_saved_before_directions_are_generated_again(monkeypatch):
    body, generated = generate_with(monkeypatch, saved_directions=None)
    assert body["reused"] is False and len(generated) == 1
    assert [r["id"] for r in body["routes"]] == [3, 4]
