# app/services/routing_service.py

import json
from urllib import request, error
from app.core.config import settings

URL = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"

HEADERS = {
    "Authorization": settings.ors_api_key,
    "Content-Type": "application/json",
    "Accept": "application/geo+json, application/json",
}

def format_duration(seconds: int) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h {m}m"

def get_single_route(start_lon: float, start_lat: float, end_lon: float, end_lat: float, preference: str = "fastest", avoid_features: list = None) -> dict:
    """
    Calls ORS API to generate a route based on coordinates and preferences.
    """
    body = {
        "coordinates": [[start_lon, start_lat], [end_lon, end_lat]],
        "preference": preference,
        "elevation": True,
        "extra_info": ["surface", "waytype", "steepness", "suitability", "tollways", "traildifficulty", "roadaccessrestrictions"],
    }
    
    if avoid_features:
        body["options"] = {"avoid_features": avoid_features}
        
    req = request.Request(URL, data=json.dumps(body).encode("utf-8"), headers=HEADERS, method="POST")

    try:
        with request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as e:
        print(f"HTTP {e.code} {e.reason}")
        print(e.read().decode("utf-8", errors="replace")[:1000])
        raise 
        
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
    }

def get_route_options(start_lon: float, start_lat: float, end_lon: float, end_lat: float) -> dict:
    """
    Generates multiple route candidates (e.g., fastest, backroads).
    """
    return {
        "fastest": get_single_route(
            start_lon, start_lat, end_lon, end_lat, 
            preference="fastest"
        ),
        "backroads": get_single_route(
            start_lon, start_lat, end_lon, end_lat,
            preference="shortest",
            avoid_features=["highways"],
        ),
    }

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