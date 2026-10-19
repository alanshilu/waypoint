"""
Campsites and places to eat near a trip's stops, from OpenStreetMap through the Overpass API.

OpenRouteService's POI search is capped at about 50 km² per request (a ~3.5 km box), which rarely
reaches a campsite from an overnight stop, so this queries Overpass instead: the same OSM data,
searched within CAMPING_RADIUS_KM / FOOD_RADIUS_KM of each point, with the tags that help choose.

Everything a place says about itself (facts) comes from its OSM tags; nothing is inferred.
Overpass is a free public service with a fair-use policy: all points go in one request, results
are cached for CACHE_TTL_S, and a User-Agent names the app.
"""

from __future__ import annotations

import json
import math
import threading
import time
from urllib import error, parse, request

from app.core.config import settings
from app.services import poi_service

CAMPING_RADIUS_KM = 25.0  # about 15 miles: a short drive off the route at the end of the day
FOOD_RADIUS_KM = 5.0
# Overnight and lunch points on backroads are often far from a town: food searches that find nothing
# within FOOD_RADIUS_KM are repeated once out to this radius (about 12 miles)
FOOD_WIDE_RADIUS_KM = 20.0
PLACES_PER_GROUP = 6
CACHE_TTL_S = 24 * 3600
CACHE_MAX_ENTRIES = 500
# Public Overpass servers can be slow under load (38-50 s measured on 2026-10-19), so the first server
# gets up to TIMEOUT_S and later ones only what's left: in practice they cover fast failures (429, 504).
# One find_places call takes at most OVERPASS_BUDGET_S in all, inside the agent tool's 150 s timeout.
TIMEOUT_S = 85
OVERPASS_BUDGET_S = 100
# The wider food round only starts with at least this much of the budget left
WIDE_ROUND_MIN_S = 20
# OpenRouteService's POI search, used for food when Overpass is down. Its 50 km2 area limit is measured
# in Web Mercator, which inflates ground area by 1/cos(lat)^2, so the largest box is 7.07 km * cos(lat)
# on a side: a half side of ORS_FOOD_HALF_SIDE_KM * cos(lat) (with a margin), about 1.6 miles at 37 N
ORS_FOOD_HALF_SIDE_KM = 3.2
ORS_FOOD_CATEGORY_IDS = [570, 566, 564, 567]  # restaurant, fast_food, cafe, food_court
USER_AGENT = "Waypoint road-trip planner (https://github.com/alanshilu/waypoint)"

KINDS = ("camping", "food")
CAMPING_TAGS = ("camp_site", "caravan_site")  # tourism=*
FOOD_TAGS = ("restaurant", "fast_food", "cafe", "food_court")  # amenity=*


class PlacesError(Exception):
    """Overpass could not answer: it timed out, was busy (429), or failed."""

    def __init__(self, message: str, timed_out: bool = False):
        super().__init__(message)
        self.timed_out = timed_out


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _kind_of(tags: dict) -> str | None:
    if tags.get("tourism") in CAMPING_TAGS:
        return "camping"
    if tags.get("amenity") in FOOD_TAGS:
        return "food"
    return None


def _usable(tags: dict) -> bool:
    """A place a traveller can actually go to: named, not private, not hike-in only."""
    if not tags.get("name"):
        return False
    if tags.get("access") in ("private", "no"):
        return False
    if tags.get("backcountry") == "yes":
        return False
    return tags.get("disused") != "yes"


def _yes(tags: dict, key: str) -> bool:
    return tags.get(key) in ("yes", "designated")


def facts_of(kind: str, tags: dict) -> list[str]:
    """Short facts, each straight from an OSM tag, that help a traveller choose."""
    facts: list[str] = []
    if kind == "camping":
        if tags.get("tourism") == "caravan_site":
            facts.append("RV park")
        if _yes(tags, "tents"):
            facts.append("tents allowed")
        elif tags.get("tents") == "no":
            facts.append("no tents")
        if _yes(tags, "caravans") and tags.get("tourism") != "caravan_site":
            facts.append("RVs allowed")
        if _yes(tags, "toilets"):
            facts.append("toilets")
        if _yes(tags, "shower") or _yes(tags, "showers"):
            facts.append("showers")
        if _yes(tags, "drinking_water"):
            facts.append("drinking water")
        if tags.get("power_supply") == "yes":
            facts.append("power hookups")
        if tags.get("fee") == "no":
            facts.append("free")
        elif tags.get("fee") == "yes":
            facts.append("fee")
        if tags.get("reservation") in ("required", "recommended", "yes", "no"):
            facts.append(f"reservations: {tags['reservation']}")
        if tags.get("operator"):
            facts.append(f"run by {tags['operator']}")
    else:
        facts.append(tags.get("amenity", "").replace("_", " "))
        if tags.get("cuisine"):
            facts.append(tags["cuisine"].replace("_", " ").replace(";", ", "))
        if tags.get("opening_hours"):
            facts.append(f"hours: {tags['opening_hours']}")
        if tags.get("diet:vegetarian") in ("yes", "only"):
            facts.append("vegetarian options")
        if tags.get("diet:vegan") in ("yes", "only"):
            facts.append("vegan options")
        if _yes(tags, "takeaway"):
            facts.append("takeaway")
        if _yes(tags, "outdoor_seating"):
            facts.append("outdoor seating")
    return [f for f in facts if f]


def _score(kind: str, distance_mi: float, tags: dict) -> float:
    """Lower is better: distance, less a little for each fact that makes the choice easier to trust."""
    known = 0
    if kind == "camping":
        known += sum(_yes(tags, k) for k in ("toilets", "drinking_water", "shower"))
        known += 1 if tags.get("website") or tags.get("reservation") else 0
        return distance_mi - 0.75 * known
    known += 1 if tags.get("opening_hours") else 0
    known += 1 if tags.get("cuisine") else 0
    return distance_mi - 0.3 * known


def _place(element: dict, kind: str, lat: float, lon: float) -> dict:
    tags = element.get("tags") or {}
    plat = element.get("lat", (element.get("center") or {}).get("lat"))
    plon = element.get("lon", (element.get("center") or {}).get("lon"))
    distance_mi = _km(lat, lon, plat, plon) / 1.609344
    place = {
        "id": f"osm:{element['type']}/{element['id']}",
        "kind": kind,
        "category": tags.get("tourism") if kind == "camping" else tags.get("amenity"),
        "name": tags["name"],
        "lat": round(plat, 5),
        "lon": round(plon, 5),
        "distance_mi": round(distance_mi, 1),
        "facts": facts_of(kind, tags),
    }
    if tags.get("website"):
        place["website"] = tags["website"]
    place["_score"] = _score(kind, distance_mi, tags)
    return place


# ---- Cache: (kind, lat, lon rounded to ~1 km) -> (saved at, places) ----

_cache: dict[tuple, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def _cache_key(kind: str, lat: float, lon: float) -> tuple:
    return kind, round(lat, 2), round(lon, 2)


def _cached(key: tuple) -> dict | None:
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL_S:
            return hit[1]
        return None


def _store(key: tuple, result: dict) -> None:
    with _cache_lock:
        if len(_cache) >= CACHE_MAX_ENTRIES:
            _cache.pop(min(_cache, key=lambda k: _cache[k][0]))
        _cache[key] = (time.time(), result)


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _bbox(lat: float, lon: float, radius_km: float) -> str:
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(0.1, math.cos(math.radians(lat))))
    return f"{lat - dlat:.4f},{lon - dlon:.4f},{lat + dlat:.4f},{lon + dlon:.4f}"


def build_query(searches: list[tuple[str, float, float]], food_radius_km: float = FOOD_RADIUS_KM) -> str:
    """One Overpass QL query for every (kind, lat, lon) search; boxes, trimmed to the radius afterwards."""
    parts = []
    for kind, lat, lon in searches:
        if kind == "camping":
            parts.append(f'nwr["tourism"~"^({"|".join(CAMPING_TAGS)})$"]({_bbox(lat, lon, CAMPING_RADIUS_KM)});')
        else:
            parts.append(f'nwr["amenity"~"^({"|".join(FOOD_TAGS)})$"]({_bbox(lat, lon, food_radius_km)});')
    return f"[out:json][timeout:{TIMEOUT_S - 5}];({''.join(parts)});out center tags;"


def _overpass_once(url: str, query: str, timeout: float) -> list[dict]:
    data = parse.urlencode({"data": query}).encode()
    req = request.Request(url, data=data, headers={"User-Agent": USER_AGENT}, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")).get("elements", [])
    except error.HTTPError as e:
        busy = e.code in (429, 502, 503, 504)
        raise PlacesError(f"OpenStreetMap (Overpass) is {'busy' if busy else 'failing'}: HTTP {e.code}",
                          timed_out=e.code == 504) from e
    except TimeoutError as e:
        raise PlacesError(f"OpenStreetMap (Overpass) did not answer within {timeout:.0f} s", timed_out=True) from e
    except error.URLError as e:
        if isinstance(e.reason, TimeoutError):
            raise PlacesError(f"OpenStreetMap (Overpass) did not answer within {timeout:.0f} s", timed_out=True) from e
        raise PlacesError(f"OpenStreetMap (Overpass) is unreachable: {e.reason}") from e


def _overpass(query: str, budget_s: float = OVERPASS_BUDGET_S) -> list[dict]:
    """The first answer from the configured Overpass servers, within budget_s. Raises PlacesError."""
    deadline = time.monotonic() + budget_s
    last: PlacesError | None = None
    for url in settings.overpass_url_list:
        left = deadline - time.monotonic()
        if left < 5:
            break
        try:
            return _overpass_once(url, query, min(TIMEOUT_S, left))
        except PlacesError as e:
            last = e
    raise last or PlacesError("No OpenStreetMap (Overpass) server is configured")


def ors_half_side_km(lat: float) -> float:
    """Half the side of the largest box OpenRouteService's POI search accepts at this latitude."""
    return ORS_FOOD_HALF_SIDE_KM * math.cos(math.radians(lat))


def _ors_food(lat: float, lon: float) -> list[dict]:
    """Food near a point from OpenRouteService, for when Overpass is down. Elements shaped like Overpass's."""
    half = ors_half_side_km(lat)
    dlat = half / 111.0
    dlon = half / (111.0 * max(0.1, math.cos(math.radians(lat))))
    features = poi_service.fetch_pois_from_ors(lon - dlon, lat - dlat, lon + dlon, lat + dlat,
                                               category_ids=ORS_FOOD_CATEGORY_IDS)
    elements = []
    for f in features:
        props = f.get("properties") or {}
        lon_, lat_ = (f.get("geometry") or {}).get("coordinates", [None, None])[:2]
        category = next(iter((props.get("category_ids") or {}).values()), {}).get("category_name")
        tags = {**(props.get("osm_tags") or {}), "amenity": category}
        if lat_ is None or category not in FOOD_TAGS:
            continue
        elements.append({"type": {1: "node", 2: "way", 3: "relation"}.get(props.get("osm_type"), "node"),
                         "id": props.get("osm_id"), "lat": lat_, "lon": lon_, "tags": tags})
    return elements


def _candidates(elements: list[dict]) -> list[tuple[str, dict]]:
    """(kind, element) for each usable place, once each."""
    seen = set()
    out = []
    for element in elements:
        key = (element.get("type"), element.get("id"))
        tags = element.get("tags") or {}
        kind = _kind_of(tags)
        if key in seen or kind is None or not _usable(tags):
            continue
        if "lat" not in element and "center" not in element:
            continue
        seen.add(key)
        out.append((kind, element))
    return out


def _ranked(candidates: list[tuple[str, dict]], kind: str, lat: float, lon: float, radius_km: float) -> list[dict]:
    places = [_place(e, k, lat, lon) for k, e in candidates if k == kind]
    places = [p for p in places if p["distance_mi"] * 1.609344 <= radius_km + 0.05]
    places.sort(key=lambda p: p["_score"])
    return places[:PLACES_PER_GROUP]


def _widen_empty_food(food_searches: list[tuple], fresh: dict[tuple, dict], started: float) -> bool:
    """
    Repeats food searches that found nothing, out to FOOD_WIDE_RADIUS_KM, in one more Overpass request,
    updating fresh in place. Returns False when that round couldn't run or failed (so the empty results
    aren't cached), True otherwise.
    """
    empty = [s for s in food_searches if not fresh[_cache_key(*s)]["places"]]
    if not empty:
        return True
    near_mi = round(FOOD_RADIUS_KM / 1.609344, 1)
    wide_mi = round(FOOD_WIDE_RADIUS_KM / 1.609344, 1)
    left = OVERPASS_BUDGET_S - (time.monotonic() - started)
    if left < WIDE_ROUND_MIN_S:
        for s in empty:
            fresh[_cache_key(*s)]["note"] = f"Nothing within {near_mi} mi; no time left to search further"
        return False
    try:
        candidates = _candidates(_overpass(build_query(empty, FOOD_WIDE_RADIUS_KM), left))
    except PlacesError as e:
        for s in empty:
            fresh[_cache_key(*s)]["note"] = f"Nothing within {near_mi} mi; the wider search failed: {e}"
        return False
    for kind, lat, lon in empty:
        found = _ranked(candidates, kind, lat, lon, FOOD_WIDE_RADIUS_KM)
        note = (f"Nothing within {near_mi} mi, so searched out to {wide_mi} mi" if found
                else f"Nothing within {wide_mi} mi")
        fresh[_cache_key(kind, lat, lon)] = {"places": found, "source": "openstreetmap",
                                             "radius_km": FOOD_WIDE_RADIUS_KM, "note": note}
    return True


def find_places(points: list[dict]) -> list[dict]:
    """
    points: [{"near": label, "lat", "lon", "kinds": ["camping", "food"]}].
    Returns one group per (point, kind):
        {"near", "kind", "lat", "lon", "radius_mi", "source", "places": [...], "note"?}
    each group's places ranked best first, at most PLACES_PER_GROUP.

    One Overpass request covers every search not already cached; food searches that find nothing are
    repeated once out to FOOD_WIDE_RADIUS_KM, all within OVERPASS_BUDGET_S. If Overpass is down, food
    falls back to OpenRouteService (within about 1.6 miles) and campsites come back empty with a note.
    """
    started = time.monotonic()
    searches = list(dict.fromkeys((kind, p["lat"], p["lon"]) for p in points for kind in dict.fromkeys(p["kinds"])))
    missing = [s for s in searches if _cached(_cache_key(*s)) is None]
    # this call's uncached results: key -> {"places", "source", "radius_km", "note"?}
    fresh: dict[tuple, dict] = {}

    if missing:
        try:
            candidates = _candidates(_overpass(build_query(missing), OVERPASS_BUDGET_S))
        except PlacesError as e:
            for kind, lat, lon in missing:
                key = _cache_key(kind, lat, lon)
                if kind == "camping":
                    fresh[key] = {"places": [], "source": "none", "note": f"Campsite search unavailable: {e}"}
                    continue
                try:
                    half = ors_half_side_km(lat)
                    found = _ranked(_candidates(_ors_food(lat, lon)), "food", lat, lon, half)
                    fresh[key] = {"places": found, "source": "openrouteservice", "radius_km": half,
                                  "note": f"{e}; searched a smaller area ({half / 1.609344:.1f} mi) instead"}
                except Exception as fallback:  # noqa: BLE001 - reported in the note
                    fresh[key] = {"places": [], "source": "none",
                                  "note": f"Food search unavailable: {e}; fallback failed: {fallback}"}
        else:
            for kind, lat, lon in missing:
                radius = CAMPING_RADIUS_KM if kind == "camping" else FOOD_RADIUS_KM
                fresh[_cache_key(kind, lat, lon)] = {"places": _ranked(candidates, kind, lat, lon, radius),
                                                     "source": "openstreetmap", "radius_km": radius}
            complete = _widen_empty_food([s for s in missing if s[0] == "food"], fresh, started)
            for kind, lat, lon in missing:
                key = _cache_key(kind, lat, lon)
                if kind == "camping" or complete:  # only complete answers are cached
                    _store(key, fresh[key])

    groups = []
    for p in points:
        for kind in dict.fromkeys(p["kinds"]):
            key = _cache_key(kind, p["lat"], p["lon"])
            result = fresh.get(key) or _cached(key) or {"places": [], "source": "none"}
            radius = result.get("radius_km") or (CAMPING_RADIUS_KM if kind == "camping" else FOOD_RADIUS_KM)
            group = {
                "near": p["near"],
                "kind": kind,
                "lat": p["lat"],
                "lon": p["lon"],
                "radius_mi": round(radius / 1.609344, 1),
                "source": result["source"],
                "places": [{k: v for k, v in place.items() if k != "_score"} for place in result["places"]],
            }
            if result.get("note"):
                group["note"] = result["note"]
            groups.append(group)
    return groups
