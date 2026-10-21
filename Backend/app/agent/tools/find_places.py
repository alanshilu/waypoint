import requests

from app.agent.tools.geocode_location import BASE_URL
from app.agent.tools.http import check

# Connect timeout only: the search waits for OpenStreetMap however long it takes, and the app tells the user
CONNECT_TIMEOUT_S = 10


def find_places(points: list[dict]) -> dict:
    """Campsites and places to eat near the trip's stops, ranked, from OpenStreetMap."""
    response = requests.post(f"{BASE_URL}/places/search", json={"points": points}, timeout=(CONNECT_TIMEOUT_S, None))
    if response.status_code in (400, 422):
        return {"error": response.json().get("detail", response.text)}
    check(response)
    return response.json()


TOOL_SCHEMA = {
    "name": "find_places",
    "description": (
        "Finds campsites (within about 15 miles) and places to eat (within about 3 miles, or 12 when nothing is "
        "closer; the group's radius_mi and note say which) near points on the trip, "
        "from OpenStreetMap. One call takes every point: each overnight stop from plan_stops with kinds "
        "['camping', 'food'], and each lunch stop from plan_stops (lunch_stops) with kinds ['food']. Returns one "
        "group per point and kind, its places ranked best first, each with an id, name, distance_mi from the point "
        "and facts taken from OpenStreetMap (toilets, showers, tents allowed, fee, cuisine, hours...). A group may "
        "be empty, or carry a note when the search was unavailable."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "points": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "near": {"type": "string", "description": "The plan_stops stop id or lunch_stops id"},
                        "lat": {"type": "number"},
                        "lon": {"type": "number"},
                        "kinds": {"type": "array", "items": {"type": "string", "enum": ["camping", "food"]}},
                    },
                    "required": ["near", "lat", "lon", "kinds"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["points"],
        "additionalProperties": False,
    },
}
