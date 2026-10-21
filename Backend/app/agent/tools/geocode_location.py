import requests

from app.agent.tools.http import check
from app.core.config import settings

BASE_URL = settings.api_base_url


def geocode_location(query: str) -> dict:
    """Turns a place name into coordinates, e.g. 'San Francisco, CA' -> lat/lon."""
    response = requests.get(
        f"{BASE_URL}/location/search",
        params={"q": query},
        timeout=10,
    )
    check(response)
    results = response.json()["results"]
    if not results:
        return {"error": f"No location found for '{query}'"}
    return results[0]  # {"label": ..., "lat": ..., "lon": ...}


TOOL_SCHEMA = {
    "name": "geocode_location",
    "description": "Converts a place name (city, landmark, address) into coordinates. Call this for BOTH the origin and destination before creating a trip.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "e.g. 'San Francisco, CA' or 'Yosemite Valley, CA'"},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}
