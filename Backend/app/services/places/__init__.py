"""
Campsites and places to eat near a trip's stops. The pieces, each replaceable:

  osm.py           what counts as a campsite or place to eat, facts from tags, ranking (pure)
  sources.py       the PlaceSource and FoodFallback contracts, and PlacesError
  overpass.py      OverpassSource: OpenStreetMap through public Overpass servers, hedged
  ors_fallback.py  OrsFoodFallback: food from OpenRouteService when Overpass is down
  cache.py         PlacesCache over a CacheStore (the places_cache table)
  finder.py        PlacesFinder: puts them together

This module wires the defaults; get_places_finder is the FastAPI dependency.
"""

from functools import lru_cache

from app.core.config import settings
from app.core.db import SessionLocal
from app.services.places.cache import DatabaseStore, PlacesCache
from app.services.places.finder import PlacesFinder
from app.services.places.ors_fallback import OrsFoodFallback
from app.services.places.overpass import OverpassSource
from app.services.places.sources import FoodFallback, PlaceSource, PlacesError

__all__ = ["FoodFallback", "PlaceSource", "PlacesError", "PlacesFinder", "find_places", "get_places_finder"]


@lru_cache(maxsize=1)
def get_places_finder() -> PlacesFinder:
    """The app's finder: Overpass, the ORS food fallback, and the cache backed by the database. One per process."""
    return PlacesFinder(
        source=OverpassSource(settings.overpass_url_list),
        food_fallback=OrsFoodFallback(),
        cache=PlacesCache(DatabaseStore(SessionLocal)),
    )


def find_places(points: list[dict]) -> list[dict]:
    """PlacesFinder.find with the app's finder."""
    return get_places_finder().find(points)
