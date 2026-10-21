"""
Campsites and places to eat near a trip's stops. OpenRouteService's POI search is capped at about 50 km²
per request (a ~3.5 km box), which rarely reaches a campsite from an overnight stop, so the main source is
OpenStreetMap: the same data, searched within CAMPING_RADIUS_KM / FOOD_RADIUS_KM of each point, with the
tags that help choose.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from app.services.places import osm
from app.services.places.cache import PlacesCache, cache_key
from app.services.places.osm import FOOD_RADIUS_KM, FOOD_WIDE_RADIUS_KM, KM_PER_MILE, Search
from app.services.places.sources import FoodFallback, PlaceSource, PlacesError

# One find_places call takes at most this long in all; when the main source can't answer in time, food
# falls back (about a second)
BUDGET_S = 50
# The wider food round only starts with at least this much of the budget left
WIDE_ROUND_MIN_S = 10


class PlacesFinder:
    """
    Finds places with a main source, a food fallback for when it's down, and a cache. Each is passed in, so
    another source (or a fake, in tests) needs no change here.
    """

    def __init__(self, source: PlaceSource, food_fallback: FoodFallback, cache: PlacesCache,
                 budget_s: float = BUDGET_S, wide_round_min_s: float = WIDE_ROUND_MIN_S,
                 clock: Callable[[], float] = time.monotonic):
        self.source = source
        self.food_fallback = food_fallback
        self.cache = cache
        self.budget_s = budget_s
        self.wide_round_min_s = wide_round_min_s
        self._clock = clock

    def find(self, points: list[dict]) -> list[dict]:
        """
        points: [{"near": label, "lat", "lon", "kinds": ["camping", "food"]}].
        Returns one group per (point, kind):
            {"near", "kind", "lat", "lon", "radius_mi", "source", "places": [...], "note"?}
        each group's places ranked best first, at most PLACES_PER_GROUP.

        One request to the source covers every search not already cached; food searches that find nothing
        are repeated once out to FOOD_WIDE_RADIUS_KM, all within budget_s. If the source is down, food comes
        from the fallback and campsites come back empty with a note. Only complete answers are cached.
        """
        started = self._clock()
        searches: list[Search] = list(dict.fromkeys((kind, p["lat"], p["lon"]) for p in points for kind in dict.fromkeys(p["kinds"])))
        missing_keys = set(self.cache.missing([cache_key(*s) for s in searches]))
        missing = [s for s in searches if cache_key(*s) in missing_keys]
        # this call's uncached results: key -> {"places", "source", "radius_km", "note"?}
        fresh: dict = {}

        if missing:
            try:
                found = osm.candidates(self.source.search(missing, FOOD_RADIUS_KM, self.budget_s))
            except PlacesError as e:
                for kind, lat, lon in missing:
                    fresh[cache_key(kind, lat, lon)] = (self._unavailable(e) if kind == "camping"
                                                        else self._food_from_fallback(e, lat, lon))
            else:
                for kind, lat, lon in missing:
                    within = osm.radius_km(kind)
                    fresh[cache_key(kind, lat, lon)] = {"places": osm.ranked(found, kind, lat, lon, within),
                                                       "source": self.source.name, "radius_km": within}
                complete = self._widen_empty_food([s for s in missing if s[0] == "food"], fresh, started)
                self.cache.put({cache_key(*s): fresh[cache_key(*s)] for s in missing if s[0] == "camping" or complete})

        return [self._group(p, kind, fresh) for p in points for kind in dict.fromkeys(p["kinds"])]

    @staticmethod
    def _unavailable(error: PlacesError) -> dict:
        return {"places": [], "source": "none", "note": f"Campsite search unavailable: {error}"}

    def _food_from_fallback(self, error: PlacesError, lat: float, lon: float) -> dict:
        try:
            elements, within = self.food_fallback.search(lat, lon)
            return {"places": osm.ranked(osm.candidates(elements), "food", lat, lon, within),
                    "source": self.food_fallback.name, "radius_km": within,
                    "note": f"{error}; searched a smaller area ({within / KM_PER_MILE:.1f} mi) instead"}
        except Exception as fallback:  # noqa: BLE001 - reported in the note
            return {"places": [], "source": "none",
                    "note": f"Food search unavailable: {error}; fallback failed: {fallback}"}

    def _widen_empty_food(self, food_searches: list[Search], fresh: dict, started: float) -> bool:
        """
        Repeats food searches that found nothing, out to FOOD_WIDE_RADIUS_KM, in one more request, updating
        fresh in place. Returns False when that round couldn't run or failed (so the empty results aren't
        cached), True otherwise.
        """
        empty = [s for s in food_searches if not fresh[cache_key(*s)]["places"]]
        if not empty:
            return True
        near_mi = round(FOOD_RADIUS_KM / KM_PER_MILE, 1)
        wide_mi = round(FOOD_WIDE_RADIUS_KM / KM_PER_MILE, 1)
        left = self.budget_s - (self._clock() - started)
        if left < self.wide_round_min_s:
            for s in empty:
                fresh[cache_key(*s)]["note"] = f"Nothing within {near_mi} mi; no time left to search further"
            return False
        try:
            found = osm.candidates(self.source.search(empty, FOOD_WIDE_RADIUS_KM, left))
        except PlacesError as e:
            for s in empty:
                fresh[cache_key(*s)]["note"] = f"Nothing within {near_mi} mi; the wider search failed: {e}"
            return False
        for kind, lat, lon in empty:
            places = osm.ranked(found, kind, lat, lon, FOOD_WIDE_RADIUS_KM)
            note = (f"Nothing within {near_mi} mi, so searched out to {wide_mi} mi" if places
                    else f"Nothing within {wide_mi} mi")
            fresh[cache_key(kind, lat, lon)] = {"places": places, "source": self.source.name,
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
