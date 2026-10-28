"""Share links: GET /shared/{public_id} and the plan kept for it, with the database stubbed."""

import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from geoalchemy2.shape import from_shape
from shapely.geometry import LineString, Point

from app.api.v1.endpoints import agent as agent_api
from app.api.v1.endpoints import shared as shared_api
from app.core.config import settings
from app.core.db import get_db
from app.core.rate_limit import SlidingWindowLimit
from app.main import app
from app.services import sharing, trip_service

PUBLIC_ID = uuid.UUID("6f1c2b8e-3a41-4e0b-9a51-2d6b8f0c7e11")


def route(id_, route_type, miles, seconds):
    return SimpleNamespace(
        id=id_, trip_id=41, route_type=route_type, distance_miles=miles, duration_seconds=seconds, ascent_m=900.0,
        descent_m=880.0, scenic_score=40.0, is_selected=id_ == 18,
        geometry=from_shape(LineString([(-122.42, 37.77), (-120.0, 36.0), (-118.24, 34.05)]), srid=4326),
        elevation_profile=[{"mile": 0, "m": 10}], directions=[{"instruction": "Head south"}], created_at=None)


ROUTES = [route(17, "fastest", 383.0, 23400), route(18, "backroads", 421.0, 50460)]

PLAN = {
    "planned_stops": [
        {"id": "18-1", "day": 1, "kind": "overnight", "name": "Kern County", "lat": 35.3, "lon": -119.0,
         "arrival_date": "2026-10-29", "route_id": 18},
        {"id": "18-2", "day": 2, "kind": "destination", "name": "Los Angeles", "lat": 34.05, "lon": -118.24,
         "arrival_date": "2026-10-30"},
    ],
    "places": [
        {"near": "18-1", "label": "Night 1 · Kern County", "kind": "stay", "lat": 35.3, "lon": -119.0,
         "radius_mi": 15.0, "source": "overpass", "session_id": "secret-session",
         "places": [{"id": "osm:node/1", "kind": "stay", "name": "Kern River Camp", "category": "camp_site",
                     "lat": 35.31, "lon": -119.01, "distance_mi": 1.2, "facts": ["toilets"], "recommended": True,
                     "reason": "1.2 mi away, toilets", "_score": 3.1}]},
        {"near": "18-1-lunch", "label": "Lunch, day 1 · near Gilroy", "kind": "food", "lat": 37.0, "lon": -121.5,
         "radius_mi": 3.0, "source": "none", "note": "Food search unavailable", "places": []},
    ],
    "saved_at": "2026-10-28T12:00:00+00:00",
}


def trip(**overrides):
    values = dict(id=41, public_id=PUBLIC_ID, name="SF to LA", origin_name="San Francisco, CA",
                  origin_point=from_shape(Point(-122.42, 37.77), srid=4326), destination_name="Los Angeles, CA",
                  destination_point=from_shape(Point(-118.24, 34.05), srid=4326), selected_route_id=18,
                  shared_plan=PLAN)
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def client(monkeypatch):
    saved = {"trip": trip()}
    monkeypatch.setattr(sharing, "find_by_public_id",
                        lambda db, public_id: saved["trip"] if public_id == PUBLIC_ID else None)
    monkeypatch.setattr(trip_service, "routes_to_show", lambda db, t: ROUTES)
    app.dependency_overrides[get_db] = lambda: SimpleNamespace()
    app.dependency_overrides[shared_api.get_shared_limit] = lambda: SlidingWindowLimit(100)
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(shared_api.get_shared_limit, None)


def walk(value, path=""):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from walk(v, f"{path}.{k}")
            yield f"{path}.{k}", k, v
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from walk(v, f"{path}[{i}]")


def test_shared_trip_has_routes_selection_stops_and_places(client):
    r = client.get(f"/shared/{PUBLIC_ID}")
    assert r.status_code == 200
    body = r.json()
    assert body["public_id"] == str(PUBLIC_ID)
    assert body["origin"]["name"] == "San Francisco, CA"
    assert [(x["route_type"], x["selected"]) for x in body["routes"]] == [("fastest", False), ("backroads", True)]
    assert body["routes"][1]["duration_vs_fastest"] == 2.16
    assert body["routes"][0]["geometry"]["type"] == "LineString"
    assert [s["name"] for s in body["planned_stops"]] == ["Kern County", "Los Angeles"]
    assert body["places"][0]["places"][0]["reason"] == "1.2 mi away, toilets"
    assert body["places"][1]["note"] == "Food search unavailable"


def test_shared_trip_has_no_integer_ids_or_session_data(client):
    body = client.get(f"/shared/{PUBLIC_ID}").json()
    keys = {k for _, k, _ in walk(body)}
    assert not keys & {"trip_id", "route_id", "session_id", "selected_route_id", "created_at", "updated_at", "_score"}
    for path, key, value in walk(body):
        if key == "id":
            assert isinstance(value, str) and not value.isdigit(), path
    text = json.dumps(body)
    assert "18-1" not in text and "secret-session" not in text and '"41"' not in text


def test_stop_ids_are_renumbered_consistently(client):
    body = client.get(f"/shared/{PUBLIC_ID}").json()
    assert [s["id"] for s in body["planned_stops"]] == ["stop-1", "stop-2"]
    assert body["places"][0]["near"] == "stop-1"  # still points at its stop
    assert body["places"][1]["near"] == "stop-3"  # the lunch point, renamed too


def test_trip_without_a_plan_still_shares_its_routes(client, monkeypatch):
    monkeypatch.setattr(sharing, "find_by_public_id", lambda db, public_id: trip(shared_plan=None))
    body = client.get(f"/shared/{PUBLIC_ID}").json()
    assert len(body["routes"]) == 2 and body["planned_stops"] == [] and body["places"] == []


@pytest.mark.parametrize("public_id", [str(uuid.uuid4()), "41", "not-a-uuid"])
def test_unknown_or_malformed_links_are_not_found(client, public_id):
    r = client.get(f"/shared/{public_id}")
    assert r.status_code == 404
    assert r.json()["detail"] == "Shared trip not found"


def test_rate_limited_per_address(client):
    app.dependency_overrides[shared_api.get_shared_limit] = lambda: limit
    limit = SlidingWindowLimit(2)
    assert client.get(f"/shared/{PUBLIC_ID}").status_code == 200
    assert client.get(f"/shared/{uuid.uuid4()}").status_code == 404  # misses count too
    r = client.get(f"/shared/{PUBLIC_ID}")
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1


def test_works_in_the_public_demo(client, monkeypatch):
    monkeypatch.setattr(settings, "public_demo", True)
    monkeypatch.setattr(settings, "internal_api_token", "s3cret")
    assert client.get(f"/shared/{PUBLIC_ID}").status_code == 200  # no internal header needed


def test_sliding_window_frees_up():
    now = [0.0]
    limit = SlidingWindowLimit(1, 60, clock=lambda: now[0])
    assert limit.allow("a") == (True, 0.0)
    assert limit.allow("a")[0] is False
    assert limit.allow("b")[0] is True
    now[0] = 60.0
    assert limit.allow("a")[0] is True


# --- keeping the plan -------------------------------------------------------------------------------------

def test_plan_snapshot_keeps_stops_and_places_only():
    snapshot = sharing.plan_snapshot({"trip_id": 41, "reply": "x", "session_id": "s", "planned_stops": [{"id": "1"}],
                                      "places": []})
    assert set(snapshot) == {"planned_stops", "places", "saved_at"}
    assert sharing.plan_snapshot({"trip_id": 41, "planned_stops": [], "places": []}) is None


def test_keep_plan_saves_and_never_fails_the_turn(plan_store):
    agent_api.keep_plan(plan_store, {"trip_id": 41, "planned_stops": [{"id": "1"}], "places": []})
    assert plan_store.saved[0][0] == 41

    class Broken:
        def save(self, trip_id, snapshot):
            raise RuntimeError("database down")

    agent_api.keep_plan(Broken(), {"trip_id": 41, "planned_stops": [{"id": "1"}], "places": []})  # no raise
    agent_api.keep_plan(plan_store, {"trip_id": None, "planned_stops": [{"id": "1"}], "places": []})
    assert len(plan_store.saved) == 1


def test_trip_response_carries_the_public_id():
    from app.api.v1.serializers import trip_to_dict

    assert trip_to_dict(trip(created_at=None, updated_at=None), ROUTES)["public_id"] == str(PUBLIC_ID)
