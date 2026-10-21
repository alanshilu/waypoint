"""
Geoapify Places (https://apidocs.geoapify.com/docs/places/): OpenStreetMap's places, hosted and fast, so a
search answers in seconds where public Overpass servers can stall for minutes. Results come back in the
OSM element shape the rest of the search reads, with the place's own OSM tags where Geoapify includes them.

Free plan: 3,000 credits a day, 1 credit per 20 places returned, at most 5 requests a second. Each search
asks for one kind at one point, so requests are paced; a stop costs about 6 credits (rooms, campgrounds and
food). The free plan asks for a "Powered by Geoapify" link where its results are shown.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import requests

from app.services.places.osm import CAMP_TAGS, ROOM_TAGS, STAY_RADIUS_KM, Search
from app.services.places.sources import PlacesError

URL = "https://api.geoapify.com/v2/places"
TIMEOUT_S = 30
# 5 requests a second on the free plan: start one at most every MIN_INTERVAL_S
MIN_INTERVAL_S = 0.22
WORKERS = 4

# What to ask for, per kind: (categories, how many places). Campgrounds get their own request, so a town full
# of hotels doesn't push them out of the nearest few dozen.
REQUESTS = {
    "stay": [
        (",".join(f"accommodation.{t}" for t in ROOM_TAGS), 40),
        (",".join(f"camping.{t}" for t in CAMP_TAGS), 20),
    ],
    "food": [("catering.restaurant,catering.fast_food,catering.cafe,catering.food_court", 40)],
}

# Geoapify category -> the OSM tag it stands for, when the raw tags don't say
_CATEGORY_TAGS = {f"accommodation.{t}": ("tourism", t) for t in ROOM_TAGS}
_CATEGORY_TAGS |= {f"camping.{t}": ("tourism", t) for t in CAMP_TAGS}
_CATEGORY_TAGS |= {f"catering.{t}": ("amenity", t) for t in ("restaurant", "fast_food", "cafe", "food_court")}
_OSM_TYPES = {"n": "node", "w": "way", "r": "relation", "node": "node", "way": "way", "relation": "relation"}

# (url, params, timeout_s) -> the response JSON; raises PlacesError
Get = Callable[[str, dict, float], dict]


def _get(url: str, params: dict, timeout: float) -> dict:
    try:
        response = requests.get(url, params=params, timeout=timeout)
    except requests.Timeout as e:
        raise PlacesError(f"Geoapify did not answer within {timeout:.0f} s", timed_out=True) from e
    except requests.RequestException as e:
        raise PlacesError(f"Geoapify is unreachable: {type(e).__name__}") from e
    if response.status_code == 429:
        raise PlacesError("Geoapify is rate limiting requests (HTTP 429): the day's free credits may be used up")
    if response.status_code >= 400:
        raise PlacesError(f"Geoapify answered HTTP {response.status_code}")
    return response.json()


def to_element(feature: dict) -> dict | None:
    """A Geoapify feature as an OSM element: its raw OSM tags, completed from its categories. None without a name."""
    props = feature.get("properties") or {}
    raw = dict((props.get("datasource") or {}).get("raw") or {})
    osm_type, osm_id = raw.pop("osm_type", None), raw.pop("osm_id", None)
    tags = {k: v for k, v in raw.items() if isinstance(v, (str, int, float))}
    tags = {k: str(v) for k, v in tags.items()}
    if props.get("name") and not tags.get("name"):
        tags["name"] = props["name"]
    for category in props.get("categories") or []:
        key_value = _CATEGORY_TAGS.get(category) or _CATEGORY_TAGS.get(".".join(category.split(".")[:2]))
        if key_value and key_value[0] not in tags:
            tags[key_value[0]] = key_value[1]
    if not tags.get("name") or props.get("lat") is None:
        return None
    element_type = _OSM_TYPES.get(str(osm_type))
    return {
        # OSM ids where Geoapify has them, so a place keeps the id Overpass would give it
        "type": element_type or "geoapify",
        "id": osm_id if element_type and osm_id is not None else props.get("place_id"),
        "lat": props["lat"],
        "lon": props["lon"],
        "tags": tags,
    }


class GeoapifySource:
    """A PlaceSource over Geoapify's Places API: one request per kind and point, paced to the free plan."""

    name = "geoapify"

    def __init__(self, api_key: str, get: Get = _get, min_interval_s: float = MIN_INTERVAL_S):
        self._api_key = api_key
        self._get = get
        self._min_interval_s = min_interval_s
        self._pace = threading.Lock()
        self._next_start = 0.0

    def _wait_turn(self) -> None:
        with self._pace:
            now = time.monotonic()
            wait = self._next_start - now
            self._next_start = max(now, self._next_start) + self._min_interval_s
        if wait > 0:
            time.sleep(wait)

    def _ask(self, categories: str, limit: int, lat: float, lon: float, radius_km: float) -> list[dict]:
        self._wait_turn()
        params = {
            "categories": categories,
            "filter": f"circle:{lon},{lat},{round(radius_km * 1000)}",
            "bias": f"proximity:{lon},{lat}",
            "limit": limit,
            "apiKey": self._api_key,
        }
        body = self._get(URL, params, TIMEOUT_S)
        return [e for e in (to_element(f) for f in body.get("features") or []) if e]

    def search(self, searches: list[Search], food_radius_km: float) -> list[dict]:
        """Every search's places; raises PlacesError if any request fails (the finder then tries the next source)."""
        jobs = [(categories, limit, lat, lon, STAY_RADIUS_KM if kind == "stay" else food_radius_km)
                for kind, lat, lon in searches for categories, limit in REQUESTS[kind]]
        with ThreadPoolExecutor(max_workers=min(WORKERS, len(jobs)) or 1, thread_name_prefix="geoapify") as pool:
            results = list(pool.map(lambda job: self._ask(*job), jobs))
        return [element for result in results for element in result]
