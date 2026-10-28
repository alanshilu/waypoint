import requests

from app.agent.tools import http
from app.agent.tools.http import check
from app.core.config import settings
from app.services.geocoding_service import GEOCODE_RETRY_BUDGET_S

BASE_URL = settings.api_base_url


def geocode_location(query: str) -> dict:
    """Turns a place name into coordinates, e.g. 'San Francisco, CA' -> lat/lon."""
    response = requests.get(
        f"{BASE_URL}/location/search",
        params={"q": query},
        headers=http.headers(),
        # outlast the backend's retries of the geocoder
        timeout=http.timeout(GEOCODE_RETRY_BUDGET_S + 10),
    )
    if response.status_code in (502, 504):
        return {"error": response.json().get("detail", response.text)}
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
