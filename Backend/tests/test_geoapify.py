"""Geoapify as the first source for places to stay and eat, with its HTTP calls faked."""

import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.places import PlacesError, PlacesFinder, get_places_finder
from app.services.places.cache import PlacesCache
from app.services.places.geoapify import GeoapifySource, to_element
from test_places import DictStore, FakeFallback, FakeSource, by, element

STOP = {"near": "1-1", "lat": 35.61, "lon": -119.69, "kinds": ["stay", "food"]}


def feature(name, lat, lon, categories, **raw):
    return {"type": "Feature", "properties": {
        "name": name, "lat": lat, "lon": lon, "categories": categories, "place_id": f"pid-{name}",
        "datasource": {"sourcename": "openstreetmap", "raw": raw}}}


MOTEL = feature("Motel 6 Lost Hills", 35.6155, -119.6942, ["accommodation", "accommodation.motel", "building"],
                osm_type="w", osm_id=123456, tourism="motel", brand="Motel 6", internet_access="wlan")
RV_PARK = feature("Lost Hills RV Park", 35.6209, -119.6901, ["camping", "camping.caravan_site"],
                  osm_type="n", osm_id=777, tents="yes", toilets="yes")  # no tourism tag: from its category
DINER = feature("Highway Diner", 35.612, -119.691, ["catering", "catering.restaurant", "catering.restaurant.american"],
                osm_type="n", osm_id=888, cuisine="american")


class FakeGeoapify:
    """Answers each category request with its features; records every request's parameters."""

    def __init__(self, error=None):
        self.asked: list[dict] = []
        self.error = error

    def __call__(self, url, params, timeout):
        self.asked.append(params)
        if self.error:
            raise self.error
        cats = params["categories"]
        features = [MOTEL] if cats.startswith("accommodation") else [RV_PARK] if cats.startswith("camping") else [DINER]
        return {"type": "FeatureCollection", "features": features}


def test_a_feature_becomes_an_osm_element_with_its_own_tags_and_id():
    assert to_element(MOTEL) == {"type": "way", "id": 123456, "lat": 35.6155, "lon": -119.6942,
                                 "tags": {"tourism": "motel", "brand": "Motel 6", "internet_access": "wlan",
                                          "name": "Motel 6 Lost Hills"}}
    # a tag the raw data lacks is filled in from the category (camping.caravan_site -> tourism=caravan_site)
    assert to_element(RV_PARK)["tags"]["tourism"] == "caravan_site"
    # a cuisine subcategory still maps to its parent: catering.restaurant.american -> amenity=restaurant
    assert to_element(DINER)["tags"]["amenity"] == "restaurant"


def test_a_feature_without_osm_ids_keeps_geoapifys_own_and_one_without_a_name_is_dropped():
    bare = {"properties": {"name": "Somewhere Inn", "lat": 1.0, "lon": 2.0, "categories": ["accommodation.hotel"],
                           "place_id": "abc"}}
    assert to_element(bare) == {"type": "geoapify", "id": "abc", "lat": 1.0, "lon": 2.0,
                                "tags": {"name": "Somewhere Inn", "tourism": "hotel"}}
    assert to_element({"properties": {"lat": 1.0, "lon": 2.0, "categories": ["accommodation.hotel"]}}) is None


def test_each_stop_asks_for_rooms_campgrounds_and_food_nearest_first_within_the_radius():
    get = FakeGeoapify()
    GeoapifySource("KEY", get=get, min_interval_s=0).search([("stay", 35.61, -119.69), ("food", 35.61, -119.69)], 5.0)
    by_cats = {p["categories"].split(".")[0]: p for p in get.asked}
    assert set(by_cats) == {"accommodation", "camping", "catering"}
    assert "accommodation.motel" in by_cats["accommodation"]["categories"]
    assert by_cats["camping"]["categories"] == "camping.camp_site,camping.caravan_site"
    assert by_cats["accommodation"]["filter"] == "circle:-119.69,35.61,25000"  # 15.5 mi for places to stay
    assert by_cats["catering"]["filter"] == "circle:-119.69,35.61,5000"
    assert all(p["bias"] == "proximity:-119.69,35.61" and p["apiKey"] == "KEY" for p in get.asked)
    # credits: 1 per 20 places, so a stop's three requests cost at most 2 + 1 + 2
    assert [p["limit"] for p in get.asked] == [40, 20, 40]


def test_requests_are_paced_to_the_free_plans_five_a_second():
    get = FakeGeoapify()
    started = time.monotonic()
    GeoapifySource("KEY", get=get, min_interval_s=0.1).search([("stay", 1, 1), ("stay", 2, 2)], 5.0)
    assert len(get.asked) == 4 and time.monotonic() - started >= 0.3  # 4 starts, 0.1 s apart


def test_geoapify_answers_first_and_its_places_rank_like_any_others():
    finder = PlacesFinder([GeoapifySource("KEY", get=FakeGeoapify(), min_interval_s=0), FakeSource([])],
                          FakeFallback(), PlacesCache(DictStore()))
    groups = finder.find([STOP])
    stay, food = by(groups, "1-1", "stay"), by(groups, "1-1", "food")
    assert stay["source"] == "geoapify"
    assert {p["name"] for p in stay["places"]} == {"Motel 6 Lost Hills", "Lost Hills RV Park"}
    motel = next(p for p in stay["places"] if p["name"] == "Motel 6 Lost Hills")
    assert motel["facts"] == ["motel", "Motel 6", "wifi"] and motel["id"] == "osm:way/123456"
    assert [p["name"] for p in food["places"]] == ["Highway Diner"]


def test_when_geoapify_fails_overpass_answers_instead():
    overpass = FakeSource([element(9, 35.611, -119.69, tourism="hotel", name="Overpass Inn")])
    geoapify = GeoapifySource("KEY", get=FakeGeoapify(error=PlacesError("Geoapify is rate limiting requests (HTTP 429)")),
                              min_interval_s=0)
    groups = PlacesFinder([geoapify, overpass], FakeFallback(), PlacesCache(DictStore())).find([STOP])
    stay = by(groups, "1-1", "stay")
    assert stay["source"] == "openstreetmap" and [p["name"] for p in stay["places"]] == ["Overpass Inn"]


def test_when_every_source_fails_the_fallback_note_names_each_reason():
    geoapify = GeoapifySource("KEY", get=FakeGeoapify(error=PlacesError("Geoapify answered HTTP 503")), min_interval_s=0)
    overpass = FakeSource(PlacesError("OpenStreetMap (Overpass) went silent for 210 s", timed_out=True))
    fallback = FakeFallback([element(7, 35.611, -119.69, amenity="restaurant", name="Fallback Diner")])
    food = by(PlacesFinder([geoapify, overpass], fallback, PlacesCache(DictStore())).find([STOP]), "1-1", "food")
    assert food["source"] == "openrouteservice"
    assert food["note"].startswith("Geoapify answered HTTP 503; OpenStreetMap (Overpass) went silent for 210 s; "
                                   "searched a smaller area")


@pytest.fixture
def geoapify_endpoint():
    finder = PlacesFinder([GeoapifySource("KEY", get=FakeGeoapify(), min_interval_s=0)], FakeFallback(),
                          PlacesCache(DictStore()))
    app.dependency_overrides[get_places_finder] = lambda: finder
    yield
    app.dependency_overrides.pop(get_places_finder, None)


def test_the_endpoint_credits_geoapify_when_its_results_are_shown(geoapify_endpoint):
    r = TestClient(app).post("/places/search", json={"points": [STOP]})
    assert r.json()["attribution"] == "Place data © OpenStreetMap contributors (ODbL) · Powered by Geoapify"
