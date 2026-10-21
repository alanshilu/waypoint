"""Campsites and places to eat: PlacesFinder and its parts, POST /places/search, the agent's place groups and evals."""

import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.api.v1.endpoints.agent import place_groups
from app.main import app
from app.services.places import PlacesError, PlacesFinder, get_places_finder
from app.services.places.cache import DatabaseStore, PlacesCache, cache_key
from app.services.places.finder import BUDGET_S
from app.services.places.ors_fallback import OrsFoodFallback, ors_half_side_km
from app.services.places.overpass import OverpassSource, build_query
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


# ---- Fakes for PlacesFinder's parts ----

class FakeSource:
    """A PlaceSource answering with `answer` (elements, an exception, or a function of the call number)."""

    name = "openstreetmap"

    def __init__(self, answer):
        self.answer = answer
        self.calls: list[tuple[list, float, float]] = []  # (searches, food_radius_km, budget_s)

    def search(self, searches, food_radius_km, budget_s):
        self.calls.append((list(searches), food_radius_km, budget_s))
        result = self.answer(len(self.calls)) if callable(self.answer) else self.answer
        if isinstance(result, Exception):
            raise result
        return result

    def kinds(self, call: int) -> set[str]:
        return {kind for kind, _, _ in self.calls[call][0]}


class FakeFallback:
    """A FoodFallback with these elements, searched over ORS's box at the point's latitude."""

    name = "openrouteservice"

    def __init__(self, elements=(), error=None):
        self.elements, self.error = list(elements), error

    def search(self, lat, lon):
        if self.error:
            raise self.error
        return list(self.elements), ors_half_side_km(lat)


class DictStore:
    """A CacheStore over a dict: the places_cache table without a database."""

    def __init__(self):
        self.rows: dict = {}

    def load(self, keys, max_age_s):
        return {k: self.rows[k] for k in keys if k in self.rows}

    def save(self, results, max_age_s):
        self.rows.update({k: (time.time(), r) for k, r in results.items()})


def make_finder(source, fallback=None, store=None, **options) -> PlacesFinder:
    return PlacesFinder(source, fallback or FakeFallback(), PlacesCache(store or DictStore()), **options)


def by(groups, near, kind):
    return next(g for g in groups if g["near"] == near and g["kind"] == kind)


# ---- Ranking and facts ----

def test_groups_per_point_and_kind_ranked_and_filtered():
    source = FakeSource(ELEMENTS)
    groups = make_finder(source).find([STOP, LUNCH])
    assert [(g["near"], g["kind"]) for g in groups] == [("1-1", "camping"), ("1-1", "food"), ("1-1-lunch", "food")]
    camping = by(groups, "1-1", "camping")["places"]
    # unnamed, private, hike-in and out-of-range sites are dropped
    assert [p["name"] for p in camping] == ["Bare Camp", "Lodge Camp"]
    assert by(groups, "1-1", "food")["places"][0]["name"] == "Valley Pizzeria"
    assert [p["name"] for p in by(groups, "1-1-lunch", "food")["places"]] == ["Camino Coffee"]
    assert all(g["source"] == "openstreetmap" for g in groups)
    assert len(source.calls) == 1  # one request for every point


def test_facts_come_only_from_tags():
    groups = make_finder(FakeSource(ELEMENTS)).find([STOP])
    lodge = next(p for p in by(groups, "1-1", "camping")["places"] if p["name"] == "Lodge Camp")
    assert lodge["facts"] == ["tents allowed", "toilets", "showers", "fee", "reservations: required"]
    assert lodge["id"] == "osm:node/1" and lodge["kind"] == "camping"
    assert lodge["distance_mi"] == 3.5  # 0.05° of latitude, 3.45 mi
    pizza = by(groups, "1-1", "food")["places"][0]
    assert pizza["facts"] == ["restaurant", "pizza, italian", "hours: Mo-Su 11:00-22:00"]
    assert "_score" not in pizza


def test_a_better_described_campsite_can_outrank_a_slightly_closer_one():
    # Bare Camp is 0.7 mi away with nothing known; Lodge Camp is 3.5 mi with toilets, showers and a
    # reservation policy, worth 2.25 mi: 3.45 - 2.25 = 1.2 still ranks behind 0.7
    camping = by(make_finder(FakeSource(ELEMENTS)).find([STOP]), "1-1", "camping")["places"]
    assert [p["name"] for p in camping] == ["Bare Camp", "Lodge Camp"]
    # moved to 1.5 mi, the better-described site wins: 1.5 - 2.25 < 0.7
    closer = [dict(e, lat=36.8635) if e["id"] == 1 else e for e in ELEMENTS]
    assert by(make_finder(FakeSource(closer)).find([STOP]), "1-1", "camping")["places"][0]["name"] == "Lodge Camp"


def test_cached_searches_skip_the_source():
    source = FakeSource(ELEMENTS)
    finder = make_finder(source)
    finder.find([STOP])
    finder.find([STOP])
    assert len(source.calls) == 1


def test_queries_use_boxes_not_around():
    query = build_query([("camping", 36.85, -121.40), ("food", 37.0, -121.57)])
    assert "around:" not in query
    assert query.count('nwr["tourism"') == 1 and query.count('nwr["amenity"') == 1
    assert query.startswith("[out:json][timeout:25]") and query.endswith("out center tags;")


# ---- When the source is down ----

def test_when_the_source_is_down_food_falls_back_and_camping_says_why():
    source = FakeSource(PlacesError("OpenStreetMap (Overpass) did not answer within 50 s", timed_out=True))
    fallback = FakeFallback([element(7, 36.851, -121.40, amenity="restaurant", name="Valley Pizzeria")])
    finder = make_finder(source, fallback)
    groups = finder.find([STOP])
    camping, food = by(groups, "1-1", "camping"), by(groups, "1-1", "food")
    assert camping["places"] == [] and camping["source"] == "none"
    assert camping["note"].startswith("Campsite search unavailable: OpenStreetMap (Overpass) did not answer")
    assert [p["name"] for p in food["places"]] == ["Valley Pizzeria"]
    assert food["source"] == "openrouteservice" and "searched a smaller area (1.6 mi) instead" in food["note"]
    assert food["radius_mi"] == 1.6
    # failures are not cached: the next call asks the source again, for both kinds
    source.answer = []
    finder.find([STOP])
    assert len(source.calls) >= 2 and source.kinds(1) == {"camping", "food"}


def test_a_failing_fallback_is_reported_not_raised():
    source = FakeSource(PlacesError("OpenStreetMap (Overpass) is busy: HTTP 429"))
    food = by(make_finder(source, FakeFallback(error=RuntimeError("ORS 503"))).find([STOP]), "1-1", "food")
    assert food["places"] == [] and food["source"] == "none"
    assert food["note"] == "Food search unavailable: OpenStreetMap (Overpass) is busy: HTTP 429; fallback failed: ORS 503"


def test_the_ors_fallback_reshapes_its_features_as_osm_elements():
    asked = []

    def fetch_pois(*box, category_ids):
        asked.append((box, category_ids))
        return [
            {"geometry": {"coordinates": [-121.40, 36.851]},
             "properties": {"osm_id": 7, "osm_type": 1, "osm_tags": {"name": "Valley Pizzeria"},
                            "category_ids": {"570": {"category_name": "restaurant"}}}},
            {"geometry": {"coordinates": [-121.40, 36.852]},  # not food: dropped
             "properties": {"osm_id": 8, "osm_type": 2, "category_ids": {"600": {"category_name": "fuel"}}}},
        ]

    elements, within = OrsFoodFallback(fetch_pois).search(36.85, -121.40)
    assert elements == [{"type": "node", "id": 7, "lat": 36.851, "lon": -121.40,
                         "tags": {"name": "Valley Pizzeria", "amenity": "restaurant"}}]
    assert within == pytest.approx(ors_half_side_km(36.85)) and round(within / 1.609344, 1) == 1.6
    (min_lon, min_lat, max_lon, max_lat), categories = asked[0]
    assert min_lon < -121.40 < max_lon and min_lat < 36.85 < max_lat and 570 in categories


# ---- The wider food round ----

REMOTE = {"near": "2-1", "lat": 35.0, "lon": -120.0, "kinds": ["camping", "food"]}


def test_food_found_nowhere_near_is_searched_again_further_out():
    # first round: a campsite but no food within 5 km; second round: a diner 15 km (9.3 mi) away
    def answer(call):
        if call == 1:
            return [element(20, 35.05, -120.0, tourism="camp_site", name="Remote Camp")]
        return [element(21, 35.135, -120.0, amenity="restaurant", name="Highway Diner")]

    source = FakeSource(answer)
    finder = make_finder(source)
    groups = finder.find([REMOTE])
    food = by(groups, "2-1", "food")
    assert [p["name"] for p in food["places"]] == ["Highway Diner"]
    assert food["places"][0]["distance_mi"] == 9.3
    assert food["radius_mi"] == 12.4
    assert food["note"] == "Nothing within 3.1 mi, so searched out to 12.4 mi"
    assert by(groups, "2-1", "camping")["radius_mi"] == 15.5
    # the second round asks only for the food, over the wider box, with what's left of the budget
    assert len(source.calls) == 2 and source.kinds(1) == {"food"}
    assert source.calls[1][1] == 20.0 and source.calls[1][2] <= BUDGET_S
    # and the widened answer is cached
    finder.find([REMOTE])
    assert len(source.calls) == 2


def test_no_time_for_the_wider_round_leaves_food_empty_and_uncached():
    source = FakeSource([])
    # the search starts at 0 s; by the wider round, only 5 s of the budget are left
    clock = iter([0.0, BUDGET_S - 5])
    finder = make_finder(source, clock=lambda: next(clock, BUDGET_S))
    food = by(finder.find([REMOTE]), "2-1", "food")
    assert food["places"] == [] and "no time left" in food["note"]
    assert len(source.calls) == 1
    assert finder.cache.get(cache_key("food", 35.0, -120.0)) is None
    assert finder.cache.get(cache_key("camping", 35.0, -120.0)) is not None


# ---- The endpoint and the agent's response ----

@pytest.fixture
def endpoint_finder():
    finder = make_finder(FakeSource(ELEMENTS))
    app.dependency_overrides[get_places_finder] = lambda: finder
    yield finder
    app.dependency_overrides.pop(get_places_finder, None)


def test_endpoint_validates_and_attributes(endpoint_finder):
    client = TestClient(app)
    r = client.post("/places/search", json={"points": [STOP]})
    assert r.status_code == 200
    assert "OpenStreetMap contributors" in r.json()["attribution"]
    assert [p["name"] for p in by(r.json()["groups"], "1-1", "camping")["places"]] == ["Bare Camp", "Lodge Camp"]
    assert client.post("/places/search", json={"points": [{**STOP, "kinds": ["hotels"]}]}).status_code == 422
    assert client.post("/places/search", json={"points": [STOP] * 11}).status_code == 422
    assert client.post("/places/search", json={"points": [{**STOP, "lat": 123}]}).status_code == 422


PLAN_WITH_LUNCH = SimpleNamespace(tool="plan_stops", error=None, full_result={
    "stops": [{"id": "1-1", "day": 1, "kind": "overnight", "name": "San Benito County"}],
    "lunch_stops": [{"id": "1-1-lunch", "day": 1, "kind": "lunch", "name": "Gilroy"}],
})


def test_place_groups_are_labelled_and_marked_with_the_agents_reasons():
    found = SimpleNamespace(tool="find_places", error=None,
                            full_result={"groups": make_finder(FakeSource(ELEMENTS)).find([STOP, LUNCH])})
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


# ---- Hedged Overpass requests ----

@pytest.fixture
def servers():
    """Three fake Overpass servers. Set each one's behaviour: ("ok", delay), ("http", code) or ("hang",)."""
    behaviour: dict[str, tuple] = {}
    asked: list[str] = []

    def once(url, query, timeout):
        asked.append(url)
        how = behaviour[url]
        if how[0] == "http":
            raise PlacesError(f"HTTP {how[1]}", timed_out=how[1] == 504)
        delay = how[1] if how[0] == "ok" else timeout
        time.sleep(min(delay, timeout))
        if how[0] == "ok" and delay <= timeout:
            return [{"from": url}]
        raise PlacesError(f"{url} did not answer within {timeout:.0f} s", timed_out=True)

    source = OverpassSource(["a", "b", "c"], request_once=once, hedge_after_s=0.2)
    return SimpleNamespace(source=source, behaviour=behaviour, asked=asked)


def timed(fn, *args):
    started = time.monotonic()
    try:
        return fn(*args), time.monotonic() - started
    except PlacesError as e:
        return e, time.monotonic() - started


def test_a_healthy_first_server_is_the_only_one_asked(servers):
    servers.behaviour.update(a=("ok", 0.05), b=("ok", 0.0), c=("ok", 0.0))
    assert servers.source.query("q", 10) == [{"from": "a"}]
    assert servers.asked == ["a"]


def test_a_failing_server_hands_over_at_once(servers):
    servers.behaviour.update(a=("http", 502), b=("ok", 0.0), c=("ok", 0.0))
    result, took = timed(servers.source.query, "q", 10)
    assert result == [{"from": "b"}] and servers.asked == ["a", "b"]
    assert took < servers.source.hedge_after_s  # didn't wait for the hedge timer


def test_a_stalled_server_is_overtaken_without_waiting_for_it(servers):
    servers.behaviour.update(a=("hang",), b=("ok", 0.05), c=("ok", 0.0))
    result, took = timed(servers.source.query, "q", 10)
    assert result == [{"from": "b"}]
    assert took < 1  # about hedge_after_s, not server a's timeout


def test_the_budget_bounds_the_whole_search(servers):
    servers.behaviour.update(a=("hang",), b=("hang",), c=("hang",))
    error, took = timed(servers.source.query, "q", 1.0)
    assert isinstance(error, PlacesError) and error.timed_out
    assert took < 1.5


def test_every_server_failing_reports_the_timeout_over_a_502(servers):
    servers.behaviour.update(a=("http", 502), b=("http", 504), c=("http", 429))
    error, took = timed(servers.source.query, "q", 10)
    assert isinstance(error, PlacesError) and str(error) == "HTTP 504" and error.timed_out
    assert servers.asked == ["a", "b", "c"] and took < 1


def test_search_builds_the_query_it_sends(servers):
    servers.behaviour.update(a=("ok", 0.0))
    sent = []
    source = OverpassSource(["a"], request_once=lambda url, query, timeout: sent.append(query) or [])
    source.search([("food", 37.0, -121.57)], 20.0, 10)
    assert sent == [build_query([("food", 37.0, -121.57)], 20.0)]


# ---- The places_cache table ----

def test_saved_results_answer_without_the_source():
    source, store = FakeSource(ELEMENTS), DictStore()
    finder = make_finder(source, store=store)
    finder.find([STOP])
    assert len(source.calls) == 1 and len(store.rows) == 2  # camping and food, both saved
    finder.cache.clear()  # a restart: the memory cache is gone, the table isn't
    groups = finder.find([STOP])
    assert len(source.calls) == 1
    assert [p["name"] for p in by(groups, "1-1", "camping")["places"]] == ["Bare Camp", "Lodge Camp"]


def test_failed_searches_are_not_saved():
    store = DictStore()
    make_finder(FakeSource(PlacesError("OpenStreetMap (Overpass) is busy: HTTP 429")), store=store).find([STOP])
    assert store.rows == {}


def test_an_unreachable_database_leaves_the_memory_cache_working(caplog):
    def unreachable():
        raise OperationalError("connect", {}, Exception("connection timed out"))

    finder = make_finder(FakeSource(ELEMENTS), store=DatabaseStore(unreachable))
    groups = finder.find([STOP])
    assert by(groups, "1-1", "food")["places"][0]["name"] == "Valley Pizzeria"
    assert finder.cache.get(cache_key("food", STOP["lat"], STOP["lon"])) is not None
    assert "couldn't read the database" in caplog.text and "couldn't save to the database" in caplog.text


def test_the_memory_cache_drops_its_oldest_entry_when_full():
    now = iter(range(100))
    cache = PlacesCache(max_entries=2, clock=lambda: next(now))
    cache.put({("food", 1.0, 1.0): {"n": 1}})
    cache.put({("food", 2.0, 2.0): {"n": 2}})
    cache.put({("food", 3.0, 3.0): {"n": 3}})
    assert cache.missing([("food", 1.0, 1.0), ("food", 2.0, 2.0), ("food", 3.0, 3.0)]) == [("food", 1.0, 1.0)]
