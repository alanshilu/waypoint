"""Food from OpenRouteService's POI search, for when Overpass is down."""

from __future__ import annotations

import math
from collections.abc import Callable

from app.services import poi_service
from app.services.places.osm import FOOD_TAGS

# Its 50 km2 area limit is measured in Web Mercator, which inflates ground area by 1/cos(lat)^2, so the
# largest box is 7.07 km * cos(lat) on a side: a half side of ORS_FOOD_HALF_SIDE_KM * cos(lat) (with a
# margin), about 1.6 miles at 37 N
ORS_FOOD_HALF_SIDE_KM = 3.2
ORS_FOOD_CATEGORY_IDS = [570, 566, 564, 567]  # restaurant, fast_food, cafe, food_court

# (min_lon, min_lat, max_lon, max_lat, category_ids=...) -> GeoJSON features
FetchPois = Callable[..., list[dict]]


def ors_half_side_km(lat: float) -> float:
    """Half the side of the largest box OpenRouteService's POI search accepts at this latitude."""
    return ORS_FOOD_HALF_SIDE_KM * math.cos(math.radians(lat))


def _default_fetch(*args, **kwargs) -> list[dict]:
    # looked up per call, so the ORS client stays replaceable
    return poi_service.fetch_pois_from_ors(*args, **kwargs)


class OrsFoodFallback:
    """A FoodFallback: ORS's POI features near a point, reshaped as OSM elements."""

    name = "openrouteservice"

    def __init__(self, fetch_pois: FetchPois = _default_fetch):
        self._fetch_pois = fetch_pois

    def search(self, lat: float, lon: float) -> tuple[list[dict], float]:
        half = ors_half_side_km(lat)
        dlat = half / 111.0
        dlon = half / (111.0 * max(0.1, math.cos(math.radians(lat))))
        features = self._fetch_pois(lon - dlon, lat - dlat, lon + dlon, lat + dlat, category_ids=ORS_FOOD_CATEGORY_IDS)
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
        return elements, half
