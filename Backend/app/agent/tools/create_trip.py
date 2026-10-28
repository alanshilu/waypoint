import requests

from app.agent.tools.geocode_location import BASE_URL
from app.agent.tools import http
from app.agent.tools.http import check


def create_trip(name, origin_label, origin_lat, origin_lon,
                destination_label, destination_lat, destination_lon) -> dict:
    """
    Creates a trip record and returns its trip_id. A trip with the same origin
    and destination from the last 24 hours is returned instead, with reused: true.
    """
    payload = {
        "name": name,
        "origin_name": origin_label,
        "origin_lat": origin_lat,
        "origin_lon": origin_lon,
        "destination_name": destination_label,
        "destination_lat": destination_lat,
        "destination_lon": destination_lon,
    }
    response = requests.post(f"{BASE_URL}/trips/", params={"reuse_recent": "true"}, json=payload,
                             headers=http.headers(internal=True), timeout=http.timeout(10))
    check(response)
    return response.json()  # {"trip_id": ..., "reused": bool}


TOOL_SCHEMA = {
    "name": "create_trip",
    "description": (
        "Creates a trip record once you have geocoded coordinates for both origin and destination. If a trip with "
        "the same origin and destination was created in the last 24 hours, returns that trip with reused: true."
    ),
    "strict": True,
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
        "additionalProperties": False,
    },
}
