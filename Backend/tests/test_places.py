"""Campsites and places to eat: the Overpass service, POST /places/search, the agent's place groups and evals."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints.agent import place_groups
from app.main import app
from app.services import places_service as ps
from evals.checks import Session, TurnRecord, poi_coords_grounded, stops_grounded
from test_eval_checks import BASE_STEPS, PLAN, step

STOP = {"near": "1-1", "lat": 36.85, "lon": -121.40, "kinds": ["camping", "food"]}
LUNCH = {"near": "1-1-lunch", "lat": 37.0, "lon": -121.57, "kinds": ["food"]}


def element(id_, lat, lon, **tags):
    return {"type": "node", "id": id_, "lat": lat, "lon": lon, "tags": tags}


ELEMENTS = [
    # near the overnight stop (36.85, -121.40)
    element(1, 36.90, -121.40, tourism="camp_site", name="Lodge Camp", tents="yes", toilets="yes", shower="yes",
            fee="yes", reservation="required"),
    element(2, 36.86, -121.40, tourism="camp_site", name="Bare Camp"),
    element(3, 36.86, -121.41, tourism="camp_site", name="Private Camp", access="private"),
    element(4, 36.86, -121.41, tourism="camp_site", name="Hike-in Camp", backcountry="yes"),
    element(5, 36.86, -121.41, tourism="camp_site"),  # unnamed
    element(6, 37.30, -121.40, tourism="camp_site", name="Too Far Camp"),  # ~50 km away
    element(7, 36.851, -121.40, amenity="restaurant", name="Valley Pizzeria", cuisine="pizza;italian",
            opening_hours="Mo-Su 11:00-22:00"),
    # near the lunch point (37.0, -121.57)
    element(8, 37.001, -121.57, amenity="cafe", name="Camino Coffee"),
    element(9, 36.90, -121.40, amenity="bar", name="Not Food For Us"),
]


@pytest.fixture(autouse=True)
def fresh_cache():
    ps.clear_cache()
    yield
    ps.clear_cache()


@pytest.fixture
def overpass(monkeypatch):
    queries = []

    def fake(query, budget_s=None):
        queries.append(query)
        return ELEMENTS

    monkeypatch.setattr(ps, "_overpass", fake)
    return queries


def by(groups, near, kind):
    return next(g for g in groups if g["near"] == near and g["kind"] == kind)


def test_groups_per_point_and_kind_ranked_and_filtered(overpass):
    groups = ps.find_places([STOP, LUNCH])
    assert [(g["near"], g["kind"]) for g in groups] == [("1-1", "camping"), ("1-1", "food"), ("1-1-lunch", "food")]
    camping = by(groups, "1-1", "camping")["places"]
    # unnamed, private, hike-in and out-of-range sites are dropped
    assert [p["name"] for p in camping] == ["Bare Camp", "Lodge Camp"]
    assert by(groups, "1-1", "food")["places"][0]["name"] == "Valley Pizzeria"
    assert [p["name"] for p in by(groups, "1-1-lunch", "food")["places"]] == ["Camino Coffee"]
    assert all(g["source"] == "openstreetmap" for g in groups)
    assert len(overpass) == 1  # one request for every point


def test_facts_come_only_from_tags(overpass):
    groups = ps.find_places([STOP])
    lodge = next(p for p in by(groups, "1-1", "camping")["places"] if p["name"] == "Lodge Camp")
    assert lodge["facts"] == ["tents allowed", "toilets", "showers", "fee", "reservations: required"]
    assert lodge["id"] == "osm:node/1" and lodge["kind"] == "camping"
    assert lodge["distance_mi"] == 3.5  # 0.05° of latitude, 3.45 mi
    pizza = by(groups, "1-1", "food")["places"][0]
    assert pizza["facts"] == ["restaurant", "pizza, italian", "hours: Mo-Su 11:00-22:00"]
    assert "_score" not in pizza


def test_a_better_described_campsite_can_outrank_a_slightly_closer_one(overpass, monkeypatch):
    # Bare Camp is 0.7 mi away with nothing known; Lodge Camp is 3.5 mi with toilets, showers and a
    # reservation policy, worth 2.25 mi: 3.45 - 2.25 = 1.2 still ranks behind 0.7
    camping = by(ps.find_places([STOP]), "1-1", "camping")["places"]
    assert [p["name"] for p in camping] == ["Bare Camp", "Lodge Camp"]
    # moved to 1.5 mi, the better-described site wins: 1.5 - 2.25 < 0.7
    closer = [dict(e, lat=36.8635) if e["id"] == 1 else e for e in ELEMENTS]
    ps.clear_cache()
    monkeypatch.setattr(ps, "_overpass", lambda query, budget_s=None: closer)
    assert by(ps.find_places([STOP]), "1-1", "camping")["places"][0]["name"] == "Lodge Camp"


def test_cached_searches_skip_overpass(overpass):
    ps.find_places([STOP])
    ps.find_places([STOP])
    assert len(overpass) == 1


def test_queries_use_boxes_not_around():
    query = ps.build_query([("camping", 36.85, -121.40), ("food", 37.0, -121.57)])
    assert "around:" not in query
    assert query.count('nwr["tourism"') == 1 and query.count('nwr["amenity"') == 1
    assert query.startswith("[out:json]") and query.endswith("out center tags;")


def test_when_overpass_is_down_food_falls_back_and_camping_says_why(monkeypatch):
    def down(query, budget_s=None):
        raise ps.PlacesError("OpenStreetMap (Overpass) did not answer within 50 s", timed_out=True)

    monkeypatch.setattr(ps, "_overpass", down)
    monkeypatch.setattr(ps, "_ors_food", lambda lat, lon: [element(7, 36.851, -121.40, amenity="restaurant",
                                                                    name="Valley Pizzeria")])
    groups = ps.find_places([STOP])
    camping, food = by(groups, "1-1", "camping"), by(groups, "1-1", "food")
    assert camping["places"] == [] and camping["source"] == "none"
    assert camping["note"].startswith("Campsite search unavailable: OpenStreetMap (Overpass) did not answer")
    assert [p["name"] for p in food["places"]] == ["Valley Pizzeria"]
    assert food["source"] == "openrouteservice" and "searched a smaller area (1.6 mi) instead" in food["note"]
    assert food["radius_mi"] == 1.6
    # failures are not cached: the next call tries Overpass again
    calls = []
    monkeypatch.setattr(ps, "_overpass", lambda q, budget_s=None: calls.append(q) or [])
    ps.find_places([STOP])
    assert calls and 'nwr["tourism"' in calls[0] and 'nwr["amenity"' in calls[0]


REMOTE = {"near": "2-1", "lat": 35.0, "lon": -120.0, "kinds": ["camping", "food"]}


def test_food_found_nowhere_near_is_searched_again_further_out(monkeypatch):
    # first round: a campsite but no food within 5 km; second round: a diner 15 km (9.3 mi) away
    rounds = []

    def fake(query, budget_s=None):
        rounds.append((query, budget_s))
        if len(rounds) == 1:
            return [element(20, 35.05, -120.0, tourism="camp_site", name="Remote Camp")]
        return [element(21, 35.135, -120.0, amenity="restaurant", name="Highway Diner")]

    monkeypatch.setattr(ps, "_overpass", fake)
    groups = ps.find_places([REMOTE])
    food = by(groups, "2-1", "food")
    assert [p["name"] for p in food["places"]] == ["Highway Diner"]
    assert food["places"][0]["distance_mi"] == 9.3
    assert food["radius_mi"] == 12.4
    assert food["note"] == "Nothing within 3.1 mi, so searched out to 12.4 mi"
    assert by(groups, "2-1", "camping")["radius_mi"] == 15.5
    # the second round asks only for the food, over the wider box, with what's left of the budget
    assert len(rounds) == 2 and 'nwr["tourism"' not in rounds[1][0]
    assert rounds[1][1] <= ps.OVERPASS_BUDGET_S
    # and the widened answer is cached
    ps.find_places([REMOTE])
    assert len(rounds) == 2


def test_no_time_for_the_wider_round_leaves_food_empty_and_uncached(monkeypatch):
    rounds = []
    monkeypatch.setattr(ps, "_overpass", lambda q, budget_s=None: rounds.append(q) or [])
    clock = iter([0.0, ps.OVERPASS_BUDGET_S - 5, 0.0, 0.0, 0.0, 0.0])
    monkeypatch.setattr(ps.time, "monotonic", lambda: next(clock, 0.0))
    food = by(ps.find_places([REMOTE]), "2-1", "food")
    assert food["places"] == [] and "no time left" in food["note"]
    assert len(rounds) == 1
    assert ps._cached(ps._cache_key("food", 35.0, -120.0)) is None  # noqa: SLF001
    assert ps._cached(ps._cache_key("camping", 35.0, -120.0)) is not None  # noqa: SLF001


def test_endpoint_validates_and_attributes(overpass):
    client = TestClient(app)
    r = client.post("/places/search", json={"points": [STOP]})
    assert r.status_code == 200
    assert "OpenStreetMap contributors" in r.json()["attribution"]
    assert client.post("/places/search", json={"points": [{**STOP, "kinds": ["hotels"]}]}).status_code == 422
    assert client.post("/places/search", json={"points": [STOP] * 11}).status_code == 422
    assert client.post("/places/search", json={"points": [{**STOP, "lat": 123}]}).status_code == 422


# ---- the agent's response ----

PLAN_WITH_LUNCH = SimpleNamespace(tool="plan_stops", error=None, full_result={
    "stops": [{"id": "1-1", "day": 1, "kind": "overnight", "name": "San Benito County"}],
    "lunch_stops": [{"id": "1-1-lunch", "day": 1, "kind": "lunch", "name": "Gilroy"}],
})


def test_place_groups_are_labelled_and_marked_with_the_agents_reasons(overpass):
    found = SimpleNamespace(tool="find_places", error=None, full_result={"groups": ps.find_places([STOP, LUNCH])})
    answer = {"places": [{"id": "osm:node/7", "reason": "0.1 mi from the stop, pizza"},
                         {"id": "osm:node/999", "reason": "not a real result"}]}
    groups = place_groups([PLAN_WITH_LUNCH, found], answer)
    assert [g["label"] for g in groups] == ["Night 1 · San Benito County", "Night 1 · San Benito County",
                                            "Lunch, day 1 · near Gilroy"]
    picked = [p for g in groups for p in g["places"] if p["recommended"]]
    assert [(p["name"], p["reason"]) for p in picked] == [("Valley Pizzeria", "0.1 mi from the stop, pizza")]


# ---- evals ----

def found_places(points, places):
    return step("find_places", {"points": points}, {"groups": [{"near": points[0]["near"], "kind": "food",
                                                                "places": places}]})


FORT_STOCKTON = {"near": "1:1", "lat": 30.89, "lon": -102.88, "kinds": ["food"]}
DINER = {"id": "osm:node/5", "name": "Pecos Diner", "kind": "food", "lat": 30.89, "lon": -102.88}


def test_recommended_place_ids_must_come_from_find_places():
    steps = BASE_STEPS + [PLAN, found_places([FORT_STOCKTON], [DINER])]
    ok = Session("t", [TurnRecord("p", "Eat at Pecos Diner.", {"stops": [], "places": [{"id": "osm:node/5", "reason": "x"}]}, steps)])
    bad = Session("t", [TurnRecord("p", "Eat.", {"stops": [], "places": [{"id": "osm:node/6", "reason": "x"}]}, steps)])
    assert stops_grounded(ok).passed
    result = stops_grounded(bad)
    assert not result.passed and "osm:node/6" in result.evidence[0]


def test_find_places_points_must_be_grounded():
    near = Session("t", [TurnRecord("p", "ok", None, BASE_STEPS + [PLAN, found_places([FORT_STOCKTON], [])])])
    far = Session("t", [TurnRecord("p", "ok", None, BASE_STEPS + [PLAN, found_places(
        [{**FORT_STOCKTON, "lat": 45.0, "lon": -90.0}], [])])])
    assert poi_coords_grounded(near).passed
    result = poi_coords_grounded(far)
    assert not result.passed and "find_places at 45.0,-90.0" in result.evidence[0]
