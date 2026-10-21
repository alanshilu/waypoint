"""
What PlacesFinder needs from a place data source. Any source works as long as it returns OSM-shaped
elements ({"type", "id", "lat"/"lon" or "center", "tags"}) and raises PlacesError when it can't answer.
"""

from __future__ import annotations

from typing import Protocol

from app.services.places.osm import Search


class PlacesError(Exception):
    """A source could not answer: it timed out, was busy (429), or failed."""

    def __init__(self, message: str, timed_out: bool = False):
        super().__init__(message)
        self.timed_out = timed_out


class PlaceSource(Protocol):
    """The main source: every search in one request, within budget_s."""

    #: what the results say they came from, e.g. "openstreetmap"
    name: str

    def search(self, searches: list[Search], food_radius_km: float, budget_s: float) -> list[dict]:
        """Elements near each (kind, lat, lon): campsites within the camping radius, food within food_radius_km."""
        ...


class FoodFallback(Protocol):
    """Where food comes from when the main source is down; campsites have no fallback."""

    name: str

    def search(self, lat: float, lon: float) -> tuple[list[dict], float]:
        """Food elements near the point, and the radius (km) that was searched. May raise any exception."""
        ...
