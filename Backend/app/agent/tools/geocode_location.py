import requests

BASE_URL = "http://localhost:8000"  # move to settings.api_base_url once deployed

def geocode_location(query: str) -> dict:
    """Turns a place name into coordinates, e.g. 'San Francisco, CA' -> lat/lon."""
    response = requests.get(
        f"{BASE_URL}/location/search",
        params={"q": query},
        timeout=10,
    )
    response.raise_for_status()
    results = response.json()["results"]
    if not results:
        return {"error": f"No location found for '{query}'"}
    return results[0]  # {"label": ..., "lat": ..., "lon": ...}


TOOL_SCHEMA = {
    "name": "geocode_location",
    "description": "Converts a place name (city, landmark, address) into coordinates. Call this for BOTH the origin and destination before creating a trip.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "e.g. 'San Francisco, CA' or 'Yosemite Valley, CA'"},
        },
        "required": ["query"],
    },
}
import requests

BASE_URL = "http://localhost:8000"  # move to settings.api_base_url once deployed


def geocode_location(query: str) -> dict:
    """Turns a place name into coordinates, e.g. 'San Francisco, CA' -> lat/lon."""
    res = requests.get(f"{BASE_URL}/location/search", params={"q": query})
    res.raise_for_status()
    results = res.json()["results"]
    if not results:
        return {"error": f"No location found for '{query}'"}
    return results[0]  # {"label": ..., "lat": ..., "lon": ...}


TOOL_SCHEMA = {
    "name": "geocode_location",
    "description": "Converts a place name (city, landmark, address) into coordinates. Call this for BOTH the origin and destination before creating a trip.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "e.g. 'San Francisco, CA' or 'Yosemite Valley, CA'"},
        },
        "required": ["query"],
    },
}
