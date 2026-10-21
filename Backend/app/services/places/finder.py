"""
Places to stay (campgrounds, RV parks, hotels, motels, guest houses, hostels, cabins, rentals) and to eat
near a trip's stops. OpenRouteService's POI search is capped at about 50 km² per request (a ~3.5 km box),
which rarely reaches a campground from an overnight stop, so the main source is OpenStreetMap: the same data
(ORS's POIs come from it), searched within STAY_RADIUS_KM / FOOD_RADIUS_KM of each point, with the tags that
help choose. ORS is the fallback.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.services.places import osm
from app.services.places.cache import PlacesCache, cache_key
from app.services.places.osm import FOOD_RADIUS_KM, FOOD_WIDE_RADIUS_KM, KM_PER_MILE, Search
from app.services.places.sources import Fallback, PlaceSource, PlacesError

UNAVAILABLE = {"stay": "Search for places to stay unavailable", "food": "Food search unavailable"}


class PlacesFinder:
    """
    Finds places with sources tried in order (Geoapify, then Overpass), a fallback for when they all fail, and a
    cache. Each is passed in, so another source (or a fake, in tests) needs no change here. There is no deadline:
    a slow source is waited for (the app tells the user it's still searching); only a failed one hands over.
    """

    def __init__(self, sources: PlaceSource | Sequence[PlaceSource], fallback: Fallback, cache: PlacesCache):
        self.sources = list(sources) if isinstance(sources, Sequence) else [sources]
        self.fallback = fallback
        self.cache = cache

    def _search(self, searches: list[Search], food_radius_km: float) -> tuple[list[tuple[str, dict]], str]:
        """(candidates, the name of the source that answered) from the first source that answers. Raises PlacesError."""
        errors: list[PlacesError] = []
        for source in self.sources:
            try:
                return osm.candidates(source.search(searches, food_radius_km)), source.name
            except PlacesError as e:
                errors.append(e)
        # every source failed: one error naming each reason, a timeout if any was one
        raise PlacesError("; ".join(str(e) for e in errors), timed_out=any(e.timed_out for e in errors))

    def find(self, points: list[dict]) -> list[dict]:
        """
        points: [{"near": label, "lat", "lon", "kinds": ["stay", "food"]}].
        Returns one group per (point, kind):
            {"near", "kind", "lat", "lon", "radius_mi", "source", "places": [...], "note"?}
        each group's places ranked best first, at most PLACES_PER_GROUP.

        The first source that answers covers every search not already cached; food searches that find nothing
        are repeated once out to FOOD_WIDE_RADIUS_KM. If every source fails, each search goes to the fallback
        over a smaller area. Only complete answers from a source are cached.
        """
        searches: list[Search] = list(dict.fromkeys((kind, p["lat"], p["lon"]) for p in points for kind in dict.fromkeys(p["kinds"])))
        missing_keys = set(self.cache.missing([cache_key(*s) for s in searches]))
        missing = [s for s in searches if cache_key(*s) in missing_keys]
        # this call's uncached results: key -> {"places", "source", "radius_km", "note"?}
        fresh: dict = {}

        if missing:
            try:
                found, answered_by = self._search(missing, FOOD_RADIUS_KM)
            except PlacesError as e:
                for kind, lat, lon in missing:
                    fresh[cache_key(kind, lat, lon)] = self._from_fallback(e, kind, lat, lon)
            else:
                for kind, lat, lon in missing:
                    within = osm.radius_km(kind)
                    fresh[cache_key(kind, lat, lon)] = {"places": osm.ranked(found, kind, lat, lon, within),
                                                       "source": answered_by, "radius_km": within}
                complete = self._widen_empty_food([s for s in missing if s[0] == "food"], fresh)
                self.cache.put({cache_key(*s): fresh[cache_key(*s)] for s in missing if s[0] != "food" or complete})

        return [self._group(p, kind, fresh) for p in points for kind in dict.fromkeys(p["kinds"])]

    def _from_fallback(self, error: PlacesError, kind: str, lat: float, lon: float) -> dict:
        try:
            elements, within = self.fallback.search(kind, lat, lon)
            return {"places": osm.ranked(osm.candidates(elements), kind, lat, lon, within),
                    "source": self.fallback.name, "radius_km": within,
                    "note": f"{error}; searched a smaller area ({within / KM_PER_MILE:.1f} mi) instead"}
        except Exception as fallback:  # noqa: BLE001 - reported in the note
            return {"places": [], "source": "none",
                    "note": f"{UNAVAILABLE[kind]}: {error}; fallback failed: {fallback}"}

    def _widen_empty_food(self, food_searches: list[Search], fresh: dict) -> bool:
        """
        Repeats food searches that found nothing, out to FOOD_WIDE_RADIUS_KM, in one more request, updating
        fresh in place. Returns False when that round failed (so the empty results aren't cached), True otherwise.
        """
        empty = [s for s in food_searches if not fresh[cache_key(*s)]["places"]]
        if not empty:
            return True
        near_mi = round(FOOD_RADIUS_KM / KM_PER_MILE, 1)
        wide_mi = round(FOOD_WIDE_RADIUS_KM / KM_PER_MILE, 1)
        try:
            found, answered_by = self._search(empty, FOOD_WIDE_RADIUS_KM)
        except PlacesError as e:
            for s in empty:
                fresh[cache_key(*s)]["note"] = f"Nothing within {near_mi} mi; the wider search failed: {e}"
            return False
        for kind, lat, lon in empty:
            places = osm.ranked(found, kind, lat, lon, FOOD_WIDE_RADIUS_KM)
            note = (f"Nothing within {near_mi} mi, so searched out to {wide_mi} mi" if places
                    else f"Nothing within {wide_mi} mi")
            fresh[cache_key(kind, lat, lon)] = {"places": places, "source": answered_by,
                                               "radius_km": FOOD_WIDE_RADIUS_KM, "note": note}
        return True

    def _group(self, point: dict, kind: str, fresh: dict) -> dict:
        key = cache_key(kind, point["lat"], point["lon"])
        result = fresh.get(key) or self.cache.get(key) or {"places": [], "source": "none"}
        within = result.get("radius_km") or osm.radius_km(kind)
        group = {
            "near": point["near"],
            "kind": kind,
            "lat": point["lat"],
            "lon": point["lon"],
            "radius_mi": round(within / KM_PER_MILE, 1),
            "source": result["source"],
            "places": [{k: v for k, v in place.items() if k != "_score"} for place in result["places"]],
        }
        if result.get("note"):
            group["note"] = result["note"]
        return group
