from geoalchemy2.shape import to_shape
from shapely.geometry import mapping

from app.models.poi import POI
from app.models.route import Route
from app.models.trip import Trip

# Degrees; roughly 100 m. Enough for a map, and it cuts a route from
# thousands of points to a few hundred. The full line stays in the database.
DEFAULT_SIMPLIFY_TOLERANCE = 0.001


def point_to_place(name: str, point) -> dict:
    shape = to_shape(point)  # Shapely Points are (longitude, latitude)
    return {"name": name, "lat": shape.y, "lon": shape.x}


def route_to_dict(route: Route, tolerance: float = DEFAULT_SIMPLIFY_TOLERANCE) -> dict:
    line = to_shape(route.geometry)
    if tolerance > 0:
        line = line.simplify(tolerance, preserve_topology=False)

    return {
        "id": route.id,
        "trip_id": route.trip_id,
        "route_type": route.route_type,
        "distance_miles": route.distance_miles,
        "duration_seconds": route.duration_seconds,
        "ascent_m": route.ascent_m,
        "descent_m": route.descent_m,
        "scenic_score": route.scenic_score,
        "is_selected": bool(route.is_selected),
        "geometry": mapping(line),  # GeoJSON LineString, [lon, lat] pairs
        "elevation_profile": route.elevation_profile,
        "created_at": route.created_at,
    }


def trip_to_dict(trip: Trip, routes: list[Route], tolerance: float = DEFAULT_SIMPLIFY_TOLERANCE) -> dict:
    return {
        "id": trip.id,
        "name": trip.name,
        "origin": point_to_place(trip.origin_name, trip.origin_point),
        "destination": point_to_place(trip.destination_name, trip.destination_point),
        "selected_route_id": trip.selected_route_id,
        "routes": [route_to_dict(r, tolerance) for r in routes],
        "created_at": trip.created_at,
        "updated_at": trip.updated_at,
    }


def poi_to_dict(poi: POI) -> dict:
    shape = to_shape(poi.location)
    return {
        "id": poi.id,
        "name": poi.name,
        "category": poi.category,
        "lat": shape.y,
        "lon": shape.x,
    }
