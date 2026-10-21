"""
Places to stay and to eat near a trip's stops. The pieces, each replaceable:

  osm.py           what counts as a place to stay or eat, facts from tags, ranking (pure)
  sources.py       the PlaceSource and Fallback contracts, and PlacesError
  geoapify.py      GeoapifySource: OpenStreetMap's places through Geoapify's hosted API, fast (needs a key)
  overpass.py      OverpassSource: OpenStreetMap through public Overpass servers, hedged
  ors_fallback.py  OrsFallback: places from OpenRouteService when Overpass is down
  cache.py         PlacesCache over a CacheStore (the places_cache table)
  finder.py        PlacesFinder: puts them together

This module wires the defaults; get_places_finder is the FastAPI dependency.
"""

from functools import lru_cache

from app.core.config import settings
from app.core.db import SessionLocal
from app.services.places.cache import DatabaseStore, PlacesCache
from app.services.places.finder import PlacesFinder
from app.services.places.geoapify import GeoapifySource
from app.services.places.ors_fallback import OrsFallback
from app.services.places.overpass import OverpassSource
from app.services.places.sources import Fallback, PlaceSource, PlacesError

__all__ = ["Fallback", "PlaceSource", "PlacesError", "PlacesFinder", "find_places", "get_places_finder"]


@lru_cache(maxsize=1)
def get_places_finder() -> PlacesFinder:
    """
    The app's finder: Geoapify first when GEOAPIFY_API_KEY is set, then Overpass, then the ORS fallback, with the
    cache backed by the database. One per process.
    """
    sources: list[PlaceSource] = []
    if settings.geoapify_api_key:
        sources.append(GeoapifySource(settings.geoapify_api_key))
    sources.append(OverpassSource(settings.overpass_url_list))
    return PlacesFinder(sources, fallback=OrsFallback(), cache=PlacesCache(DatabaseStore(SessionLocal)))


def find_places(points: list[dict]) -> list[dict]:
    """PlacesFinder.find with the app's finder."""
    return get_places_finder().find(points)
