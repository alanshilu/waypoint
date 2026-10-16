# app/services/db_route_service.py
import math

from sqlalchemy.orm import Session
from shapely.geometry import LineString
from geoalchemy2.shape import from_shape

from app.models.route import Route

EARTH_RADIUS_MILES = 3958.8
PROFILE_POINTS = 200


def _haversine_miles(a: list, b: list) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(h))


def build_elevation_profile(coords: list, distance_miles: float, points: int = PROFILE_POINTS) -> list[dict] | None:
    """
    Turns ORS [lon, lat, elevation_m] coordinates into evenly spaced
    {"mile", "m"} samples. Returns None when the coordinates carry no elevation.
    """
    if len(coords) < 2 or any(len(c) < 3 for c in coords):
        return None

    # Cumulative mile marker per vertex. Straight-line distance under-reads a
    # real road, so markers are scaled to end at the route's reported distance.
    miles = [0.0]
    for prev, cur in zip(coords, coords[1:]):
        miles.append(miles[-1] + _haversine_miles(prev, cur))
    measured = miles[-1]
    if measured <= 0:
        return None
    scale = distance_miles / measured if distance_miles > 0 else 1.0
    total = measured * scale

    profile = []
    j = 0
    for i in range(points + 1):
        target = total * i / points
        while j < len(miles) - 2 and miles[j + 1] * scale < target:
            j += 1
        lo, hi = miles[j] * scale, miles[j + 1] * scale
        t = (target - lo) / (hi - lo) if hi > lo else 0.0
        elevation = coords[j][2] + (coords[j + 1][2] - coords[j][2]) * t
        profile.append({"mile": round(target, 2), "m": round(elevation, 1)})

    return profile


def save_routes_to_db(db: Session, trip_id: int, routes_data: dict) -> list[Route]:
    saved_routes = []

    for route_type, data in routes_data.items():
        # Slice to ensure 2D coordinates [lon, lat]
        coords_2d = [coord[:2] for coord in data["geometry"]]

        # Convert to PostGIS Geometry
        shapely_line = LineString(coords_2d)
        postgis_geom = from_shape(shapely_line, srid=4326)

        db_route = Route(
            trip_id=trip_id,
            route_type=route_type,
            distance_miles=data["distance_miles"],
            duration_seconds=data["duration_seconds"],
            ascent_m=data.get("ascent_m", 0.0),
            descent_m=data.get("descent_m", 0.0),
            scenic_score=data.get("scenic_score", 0.0),
            elevation_profile=build_elevation_profile(data["geometry"], data["distance_miles"]),
            geometry=postgis_geom,
            is_selected=False
        )

        db.add(db_route)
        saved_routes.append(db_route)

    db.commit()

    for route in saved_routes:
        db.refresh(route)

    return saved_routes
