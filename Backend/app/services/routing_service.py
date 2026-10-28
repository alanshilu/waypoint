# app/services/routing_service.py

import contextvars
import json
from concurrent.futures import ThreadPoolExecutor
from urllib import request
from app.core.config import settings
from app.services import ors_http

URL = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"

HEADERS = {
    "Authorization": settings.ors_api_key,
    "Content-Type": "application/json",
    "Accept": "application/geo+json, application/json",
}

class RoutingError(Exception):
    """ORS could not give a route: it timed out, was unreachable, or answered with an HTTP error."""

    def __init__(self, message: str, timed_out: bool = False):
        super().__init__(message)
        self.timed_out = timed_out


def format_duration(seconds: int) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h {m}m"

def directions_from(segment: dict, coords: list) -> list[dict]:
    """
    Turn-by-turn steps from an ORS segment. Each step's start and end come from the full-resolution
    geometry (its way_points index into it), so they stay exact after the served line is simplified.
    ORS often leaves motorway steps unnamed ("-"); name is None then.
    """
    steps = []
    for step in segment.get("steps", []):
        first, last = step["way_points"]
        name = step.get("name")
        steps.append({
            "instruction": step["instruction"],
            "name": name if name and name != "-" else None,
            # ORS instruction types: 0 left, 1 right, 2/3 sharp, 4/5 slight, 6 straight, 7/8 roundabout,
            # 9 U-turn, 10 arrive, 11 depart, 12/13 keep left/right
            "type": step["type"],
            "distance_miles": round(step["distance"] / 1609.34, 2),
            "duration_seconds": round(step["duration"]),
            "start": [round(c, 5) for c in coords[first][:2]],
            "end": [round(c, 5) for c in coords[last][:2]],
        })
    return steps


def get_single_route(start_lon: float, start_lat: float, end_lon: float, end_lat: float, preference: str = "fastest", avoid_features: list = None) -> dict:
    """
    Calls ORS API to generate a route based on coordinates and preferences.
    """
    body = {
        "coordinates": [[start_lon, start_lat], [end_lon, end_lat]],
        "preference": preference,
        "elevation": True,
        "instructions": True,
        "language": "en",
        "extra_info": ["surface", "waytype", "steepness", "suitability", "tollways", "traildifficulty", "roadaccessrestrictions"],
    }
    
    if avoid_features:
        body["options"] = {"avoid_features": avoid_features}
        
    req = request.Request(URL, data=json.dumps(body).encode("utf-8"), headers=HEADERS, method="POST")

    # ORS_ROUTE_TIMEOUT_S for each attempt; timeouts, 429 and 5xx are retried within ORS_ROUTE_RETRY_BUDGET_S
    try:
        data = ors_http.open_json(req, timeout=settings.ors_route_timeout_s,
                                  budget_s=settings.ors_route_retry_budget_s,
                                  what=f"the {preference} route", opener=request.urlopen)
    except ors_http.OrsError as e:
        raise RoutingError(str(e), timed_out=e.timed_out) from e

    route = data["features"][0]
    props = route["properties"]
    segment = props["segments"][0]

    return {
        "distance_miles": round(segment["distance"] / 1609.34, 1),
        "duration_seconds": int(segment["duration"]), 
        "duration_hms": format_duration(segment["duration"]),
        "ascent_m": segment.get("ascent"),      
        "descent_m": segment.get("descent"),
        "geometry": route["geometry"]["coordinates"],
        "extras": props.get("extras", {}),
        "directions": directions_from(segment, route["geometry"]["coordinates"]),
    }

def get_route_options(start_lon: float, start_lat: float, end_lon: float, end_lat: float) -> dict:
    """
    Generates the fastest and backroads candidates. The two ORS requests run in
    parallel, so a slow ORS costs one timeout, not two. Raises RoutingError.
    """
    # each worker runs in a copy of this context, so the agent turn's deadline reaches both requests
    with ThreadPoolExecutor(max_workers=2) as pool:
        fastest = pool.submit(contextvars.copy_context().run, get_single_route,
                              start_lon, start_lat, end_lon, end_lat, preference="fastest")
        backroads = pool.submit(
            contextvars.copy_context().run, get_single_route, start_lon, start_lat, end_lon, end_lat,
            preference="shortest", avoid_features=["highways"],
        )
        return {"fastest": fastest.result(), "backroads": backroads.result()}

# Protect your testing code so it doesn't run when imported by FastAPI
if __name__ == "__main__":
    # Test coordinates: SF to LA
    print("Testing routing service...")
    try:
        options = get_route_options(-122.4194, 37.7749, -118.2437, 34.0522)
        print("Success! Generated routes:")
        for route_name, data in options.items():
            print(f"- {route_name.upper()}: {data['distance_miles']} miles, {data['duration_hms']}")
    except Exception as e:
        print(f"Test failed: {e}")