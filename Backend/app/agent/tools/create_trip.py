import requests

from app.agent.tools.geocode_location import BASE_URL


def create_trip(name, origin_label, origin_lat, origin_lon,
                destination_label, destination_lat, destination_lon) -> dict:
    """Creates a trip record and returns its trip_id."""
    payload = {
        "name": name,
        "origin_name": origin_label,
        "origin_lat": origin_lat,
        "origin_lon": origin_lon,
        "destination_name": destination_label,
        "destination_lat": destination_lat,
        "destination_lon": destination_lon,
    }
    response = requests.post(f"{BASE_URL}/trips/", json=payload, timeout=10)
    response.raise_for_status()
    return response.json()  # {"trip_id": ...}


TOOL_SCHEMA = {
    "name": "create_trip",
    "description": "Creates a new trip record once you have geocoded coordinates for both origin and destination.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "origin_label": {"type": "string"},
            "origin_lat": {"type": "number"},
            "origin_lon": {"type": "number"},
            "destination_label": {"type": "string"},
            "destination_lat": {"type": "number"},
            "destination_lon": {"type": "number"},
        },
        "required": ["name", "origin_label", "origin_lat", "origin_lon",
                     "destination_label", "destination_lat", "destination_lon"],
    },
}
