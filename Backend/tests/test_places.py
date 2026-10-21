"""Places to stay and to eat: PlacesFinder and its parts, POST /places/search, the agent's place groups and evals."""

import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.agent.responses import place_groups
from app.main import app
from app.services.places import PlacesError, PlacesFinder, get_places_finder
from app.services.places.cache import DatabaseStore, PlacesCache, cache_key
from app.services.places.ors_fallback import OrsFallback, ors_half_side_km
from app.services.places.overpass import OverpassSource, build_query
from evals.checks import Session, TurnRecord, poi_coords_grounded, stops_grounded
from test_eval_checks import BASE_STEPS, PLAN, step

STOP = {"near": "1-1", "lat": 36.85, "lon": -121.40, "kinds": ["stay", "food"]}
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
        self.calls: list[tuple[list, float]] = []  # (searches, food_radius_km)

    def search(self, searches, food_radius_km):
        self.calls.append((list(searches), food_radius_km))
        result = self.answer(len(self.calls)) if callable(self.answer) else self.answer
        if isinstance(result, Exception):
            raise result
        return result

    def kinds(self, call: int) -> set[str]:
        return {kind for kind, _, _ in self.calls[call][0]}


class FakeFallback:
    """A Fallback with these elements, searched over ORS's box at the point's latitude; records the kinds asked."""

    name = "openrouteservice"

    def __init__(self, elements=(), error=None):
        self.elements, self.error = list(elements), error
        self.kinds: list[str] = []

    def search(self, kind, lat, lon):
        self.kinds.append(kind)
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
    assert [(g["near"], g["kind"]) for g in groups] == [("1-1", "stay"), ("1-1", "food"), ("1-1-lunch", "food")]
    stay = by(groups, "1-1", "stay")["places"]
    # unnamed, private, hike-in and out-of-range sites are dropped
    assert [p["name"] for p in stay] == ["Bare Camp", "Lodge Camp"]
    assert by(groups, "1-1", "food")["places"][0]["name"] == "Valley Pizzeria"
    assert [p["name"] for p in by(groups, "1-1-lunch", "food")["places"]] == ["Camino Coffee"]
    assert all(g["source"] == "openstreetmap" for g in groups)
    assert len(source.calls) == 1  # one request for every point


def test_facts_come_only_from_tags():
    groups = make_finder(FakeSource(ELEMENTS)).find([STOP])
    lodge = next(p for p in by(groups, "1-1", "stay")["places"] if p["name"] == "Lodge Camp")
    assert lodge["facts"] == ["campground", "tents allowed", "toilets", "showers", "fee", "reservations: required"]
    assert lodge["id"] == "osm:node/1" and lodge["kind"] == "stay" and lodge["category"] == "camp_site"
    assert lodge["distance_mi"] == 3.5  # 0.05° of latitude, 3.45 mi
    pizza = by(groups, "1-1", "food")["places"][0]
    assert pizza["facts"] == ["restaurant", "pizza, italian", "hours: Mo-Su 11:00-22:00"]
    assert "_score" not in pizza


def test_a_better_described_campsite_can_outrank_a_slightly_closer_one():
    # Bare Camp is 0.7 mi away with nothing known; Lodge Camp is 3.5 mi with toilets, showers and a
    # reservation policy, worth 2.25 mi: 3.45 - 2.25 = 1.2 still ranks behind 0.7
    stay = by(make_finder(FakeSource(ELEMENTS)).find([STOP]), "1-1", "stay")["places"]
    assert [p["name"] for p in stay] == ["Bare Camp", "Lodge Camp"]
    # moved to 1.5 mi, the better-described site wins: 1.5 - 2.25 < 0.7
    closer = [dict(e, lat=36.8635) if e["id"] == 1 else e for e in ELEMENTS]
    assert by(make_finder(FakeSource(closer)).find([STOP]), "1-1", "stay")["places"][0]["name"] == "Lodge Camp"


def test_cached_searches_skip_the_source():
    source = FakeSource(ELEMENTS)
    finder = make_finder(source)
    finder.find([STOP])
    finder.find([STOP])
    assert len(source.calls) == 1


def test_queries_use_boxes_not_around():
    query = build_query([("stay", 36.85, -121.40), ("food", 37.0, -121.57)])
    assert "around:" not in query
    assert query.count('nwr["tourism"') == 1 and query.count('nwr["amenity"') == 1
    # Overpass's own standard maximum: the only bound on how long a search runs
    assert query.startswith("[out:json][timeout:180]") and query.endswith("out center tags;")


# ---- When the source is down ----

def test_when_the_source_is_down_places_to_stay_and_food_both_fall_back():
    source = FakeSource(PlacesError("OpenStreetMap (Overpass) went silent for 210 s", timed_out=True))
    fallback = FakeFallback([element(7, 36.851, -121.40, amenity="restaurant", name="Valley Pizzeria"),
                             element(30, 36.853, -121.40, tourism="motel", name="Valley Motel", brand="Motel 6")])
    finder = make_finder(source, fallback)
    groups = finder.find([STOP])
    stay, food = by(groups, "1-1", "stay"), by(groups, "1-1", "food")
    assert [p["name"] for p in stay["places"]] == ["Valley Motel"] and stay["source"] == "openrouteservice"
    assert stay["places"][0]["facts"] == ["motel", "Motel 6"]
    assert [p["name"] for p in food["places"]] == ["Valley Pizzeria"]
    for group in (stay, food):
        assert "searched a smaller area (1.6 mi) instead" in group["note"] and group["radius_mi"] == 1.6
    assert fallback.kinds == ["stay", "food"]
    # failures are not cached: the next call asks the source again, for both kinds
    source.answer = []
    finder.find([STOP])
    assert len(source.calls) >= 2 and source.kinds(1) == {"stay", "food"}


def test_a_failing_fallback_is_reported_not_raised():
    source = FakeSource(PlacesError("OpenStreetMap (Overpass) is busy: HTTP 429"))
    groups = make_finder(source, FakeFallback(error=RuntimeError("ORS 503"))).find([STOP])
    stay, food = by(groups, "1-1", "stay"), by(groups, "1-1", "food")
    assert food["places"] == [] and food["source"] == "none"
    assert food["note"] == "Food search unavailable: OpenStreetMap (Overpass) is busy: HTTP 429; fallback failed: ORS 503"
    assert stay["note"] == ("Search for places to stay unavailable: OpenStreetMap (Overpass) is busy: HTTP 429; "
                            "fallback failed: ORS 503")


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

    elements, within = OrsFallback(fetch_pois).search("food", 36.85, -121.40)
    assert elements == [{"type": "node", "id": 7, "lat": 36.851, "lon": -121.40,
                         "tags": {"name": "Valley Pizzeria", "amenity": "restaurant"}}]
    assert within == pytest.approx(ors_half_side_km(36.85)) and round(within / 1.609344, 1) == 1.6
    (min_lon, min_lat, max_lon, max_lat), categories = asked[0]
    assert min_lon < -121.40 < max_lon and min_lat < 36.85 < max_lat and 570 in categories


def test_the_ors_fallback_finds_places_to_stay_in_its_accommodation_categories():
    asked = []

    def fetch_pois(*box, category_ids):
        asked.append(category_ids)
        return [
            {"geometry": {"coordinates": [-121.40, 36.851]},
             "properties": {"osm_id": 31, "osm_type": 2, "osm_tags": {"name": "Inn at the Pass", "stars": "3"},
                            "category_ids": {"108": {"category_name": "hotel"}}}},
            {"geometry": {"coordinates": [-121.40, 36.852]},  # hike-in: not asked for, and dropped if returned
             "properties": {"osm_id": 32, "osm_type": 1, "osm_tags": {"name": "High Hut"},
                            "category_ids": {"101": {"category_name": "alpine_hut"}}}},
        ]

    elements, _ = OrsFallback(fetch_pois).search("stay", 36.85, -121.40)
    # each batch answers the same here; the finder drops duplicates (candidates() keys on type and id)
    assert elements[0] == {"type": "way", "id": 31, "lat": 36.851, "lon": -121.40,
                           "tags": {"name": "Inn at the Pass", "stars": "3", "tourism": "hotel"}}
    assert {e["tags"]["tourism"] for e in elements} == {"hotel"}
    # ORS takes at most 5 categories a request: the 8 go in two batches, hotels and motels first
    assert [len(batch) for batch in asked] == [5, 3] and asked[0][:2] == [108, 109]
    asked_all = {c for batch in asked for c in batch}
    assert {102, 103, 104, 105, 106, 107, 108, 109} == asked_all and not {101, 110} & asked_all


# ---- Places to stay of every kind ----

TOWN = [
    element(40, 36.86, -121.40, tourism="motel", name="Roadside Motel", brand="Super 8", internet_access="wlan"),
    element(41, 36.861, -121.40, tourism="hotel", name="Grand Hotel", stars="4", rooms="120", dog="yes"),
    element(42, 36.862, -121.40, tourism="guest_house", name="Rose B&B"),
    element(43, 36.863, -121.40, tourism="hostel", name="Backpackers"),
    element(44, 36.864, -121.40, tourism="chalet", name="Pine Cabin"),
    element(45, 36.865, -121.40, tourism="apartment", name="Creekside Rental"),
    element(46, 36.866, -121.40, tourism="motel", name="Second Motel"),
    element(47, 36.98, -121.40, tourism="camp_site", name="Far Creek Campground"),  # 9 mi out, past every room
    element(48, 36.86, -121.41, tourism="alpine_hut", name="High Hut"),  # hike-in: not a place to drive to
]


def test_motels_hotels_and_every_kind_of_stay_are_found_with_their_facts():
    stay = by(make_finder(FakeSource(TOWN)).find([STOP]), "1-1", "stay")["places"]
    names = [p["name"] for p in stay]
    assert "High Hut" not in names
    facts = {p["name"]: p["facts"] for p in stay}
    assert facts["Roadside Motel"] == ["motel", "Super 8", "wifi"]
    assert facts["Grand Hotel"] == ["hotel", "4 stars", "120 rooms", "pets allowed"]
    assert {p["category"] for p in stay} >= {"motel", "hotel", "camp_site"}


def test_a_town_full_of_rooms_still_shows_the_nearest_campground():
    # seven rooms are all closer than the campground, and only six places fit: the campground keeps a place
    stay = by(make_finder(FakeSource(TOWN)).find([STOP]), "1-1", "stay")["places"]
    assert len(stay) == 6 and "Far Creek Campground" in [p["name"] for p in stay]
    assert stay[-1]["name"] == "Far Creek Campground"  # still ranked by its own score: last, being furthest


def test_campgrounds_alone_still_rank_as_before():
    stay = by(make_finder(FakeSource(ELEMENTS)).find([STOP]), "1-1", "stay")["places"]
    assert [p["category"] for p in stay] == ["camp_site", "camp_site"]


# ---- The wider food round ----

REMOTE = {"near": "2-1", "lat": 35.0, "lon": -120.0, "kinds": ["stay", "food"]}


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
    assert by(groups, "2-1", "stay")["radius_mi"] == 15.5
    # the second round asks only for the food, over the wider box
    assert len(source.calls) == 2 and source.kinds(1) == {"food"}
    assert source.calls[1][1] == 20.0
    # and the widened answer is cached
    finder.find([REMOTE])
    assert len(source.calls) == 2


def test_the_wider_round_always_runs_however_slow_the_first_was():
    # no budget: a first round that took its time still gets the wider food search
    def answer(call):
        if call == 1:
            time.sleep(0.2)
            return [element(20, 35.05, -120.0, tourism="camp_site", name="Remote Camp")]
        return [element(21, 35.135, -120.0, amenity="restaurant", name="Highway Diner")]

    source = FakeSource(answer)
    food = by(make_finder(source).find([REMOTE]), "2-1", "food")
    assert len(source.calls) == 2 and [p["name"] for p in food["places"]] == ["Highway Diner"]


def test_a_failed_wider_round_leaves_food_empty_and_uncached():
    source = FakeSource(lambda call: [] if call == 1 else PlacesError("OpenStreetMap (Overpass) is busy: HTTP 429"))
    finder = make_finder(source)
    food = by(finder.find([REMOTE]), "2-1", "food")
    assert food["places"] == [] and food["note"] == ("Nothing within 3.1 mi; the wider search failed: "
                                                     "OpenStreetMap (Overpass) is busy: HTTP 429")
    assert finder.cache.get(cache_key("food", 35.0, -120.0)) is None
    assert finder.cache.get(cache_key("stay", 35.0, -120.0)) is not None


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
    assert [p["name"] for p in by(r.json()["groups"], "1-1", "stay")["places"]] == ["Bare Camp", "Lodge Camp"]
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
        raise PlacesError(f"{url} went silent for {timeout:.0f} s", timed_out=True)

    # a "hanging" server goes silent for the read timeout: 1 s here, so the tests don't wait 210 s
    source = OverpassSource(["a", "b", "c"], request_once=once, hedge_after_s=0.2, read_timeout_s=1.0)
    return SimpleNamespace(source=source, behaviour=behaviour, asked=asked)


def timed(fn, *args):
    started = time.monotonic()
    try:
        return fn(*args), time.monotonic() - started
    except PlacesError as e:
        return e, time.monotonic() - started


def test_a_healthy_first_server_is_the_only_one_asked(servers):
    servers.behaviour.update(a=("ok", 0.05), b=("ok", 0.0), c=("ok", 0.0))
    assert servers.source.query("q") == [{"from": "a"}]
    assert servers.asked == ["a"]


def test_a_failing_server_hands_over_at_once(servers):
    servers.behaviour.update(a=("http", 502), b=("ok", 0.0), c=("ok", 0.0))
    result, took = timed(servers.source.query, "q")
    assert result == [{"from": "b"}] and servers.asked == ["a", "b"]
    assert took < servers.source.hedge_after_s  # didn't wait for the hedge timer


def test_a_stalled_server_is_overtaken_without_waiting_for_it(servers):
    servers.behaviour.update(a=("hang",), b=("ok", 0.05), c=("ok", 0.0))
    result, took = timed(servers.source.query, "q")
    assert result == [{"from": "b"}]
    assert took < 1  # about hedge_after_s, not server a's timeout


def test_a_slow_answer_is_waited_for_with_no_deadline(servers):
    # every other server fails; the slow one is past the hedge timer many times over and still wins
    servers.behaviour.update(a=("http", 502), b=("ok", 0.8), c=("http", 429))
    result, took = timed(servers.source.query, "q")
    assert result == [{"from": "b"}] and took >= 0.8


def test_every_server_going_silent_fails_instead_of_hanging(servers):
    servers.behaviour.update(a=("hang",), b=("hang",), c=("hang",))
    error, took = timed(servers.source.query, "q")
    assert isinstance(error, PlacesError) and error.timed_out and "went silent" in str(error)
    assert took < 2  # each server's read timeout, started 0.2 s apart


def test_every_server_failing_reports_the_timeout_over_a_502(servers):
    servers.behaviour.update(a=("http", 502), b=("http", 504), c=("http", 429))
    error, took = timed(servers.source.query, "q")
    assert isinstance(error, PlacesError) and str(error) == "HTTP 504" and error.timed_out
    assert servers.asked == ["a", "b", "c"] and took < 1


def test_search_builds_the_query_it_sends_and_reads_with_the_long_timeout():
    sent = []
    source = OverpassSource(["a"], request_once=lambda url, query, timeout: sent.append((query, timeout)) or [])
    source.search([("food", 37.0, -121.57)], 20.0)
    assert sent == [(build_query([("food", 37.0, -121.57)], 20.0), 210)]  # Overpass's 180 s, plus a margin


# ---- The places_cache table ----

def test_saved_results_answer_without_the_source():
    source, store = FakeSource(ELEMENTS), DictStore()
    finder = make_finder(source, store=store)
    finder.find([STOP])
    assert len(source.calls) == 1 and len(store.rows) == 2  # stay and food, both saved
    finder.cache.clear()  # a restart: the memory cache is gone, the table isn't
    groups = finder.find([STOP])
    assert len(source.calls) == 1
    assert [p["name"] for p in by(groups, "1-1", "stay")["places"]] == ["Bare Camp", "Lodge Camp"]


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
