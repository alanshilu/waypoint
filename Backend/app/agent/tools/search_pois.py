import requests
from app.agent.tools.geocode_location import BASE_URL
from app.agent.tools import http
from app.agent.tools.http import check
from app.services.poi_service import POI_RETRY_BUDGET_S


def search_pois(lat: float, lon: float) -> dict:
    """Finds nearby points of interest (diners, fuel, campsites, etc.) around a location."""
    res = requests.get(f"{BASE_URL}/pois/search", params={"lat": lat, "lon": lon}, headers=http.headers(),
                       timeout=http.timeout(POI_RETRY_BUDGET_S + 30))
    check(res)
    return res.json()  # {"count": ..., "results": [...]}


TOOL_SCHEMA = {
    "name": "search_pois",
    "description": "Finds nearby points of interest (restaurants, fuel, campsites, attractions) around a specific location -- use for questions about a particular stop.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "lat": {"type": "number"},
            "lon": {"type": "number"},
        },
        "required": ["lat", "lon"],
        "additionalProperties": False,
    },
}