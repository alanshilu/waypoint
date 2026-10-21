from geoalchemy2.shape import to_shape
from shapely.geometry import mapping

from app.models.poi import POI
from app.models.route import Route
from app.models.trip import Trip
from app.services.scoring_service import duration_ratios

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
        # null for routes saved before directions were kept
        "directions": route.directions,
        "created_at": route.created_at,
    }


def add_duration_ratios(route_dicts: list[dict]) -> list[dict]:
    """
    Sets duration_vs_fastest (duration / the fastest route's duration, 2 dp) on
    each route. Slowness is reported here rather than inside the scenic score.
    None when the list has no fastest route.
    """
    ratios = duration_ratios({r["route_type"]: r for r in route_dicts})
    for r in route_dicts:
        r["duration_vs_fastest"] = ratios.get(r["route_type"])
    return route_dicts


def trip_to_dict(trip: Trip, routes: list[Route], tolerance: float = DEFAULT_SIMPLIFY_TOLERANCE) -> dict:
    return {
        "id": trip.id,
        "name": trip.name,
        "origin": point_to_place(trip.origin_name, trip.origin_point),
        "destination": point_to_place(trip.destination_name, trip.destination_point),
        "selected_route_id": trip.selected_route_id,
        "routes": add_duration_ratios([route_to_dict(r, tolerance) for r in routes]),
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
