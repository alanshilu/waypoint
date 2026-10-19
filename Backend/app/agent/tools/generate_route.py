import requests

from app.agent.tools.geocode_location import BASE_URL
from app.core.config import settings
from app.core.internal import internal_headers


def generate_routes(trip_id: int, force: bool = False) -> dict:
    """
    Returns the trip's fastest and backroads routes. Existing routes are reused
    (reused: true) unless force is set, which generates new ones.
    """
    response = requests.post(
        f"{BASE_URL}/routes/generate/{trip_id}",
        params={"reuse_existing": "false" if force else "true"},
        headers=internal_headers(),
        # outlast the backend's own ORS timeout, so the backend's 504 arrives instead of a client timeout
        timeout=settings.ors_route_timeout_s + 30,
    )
    if response.status_code in (502, 504):
        # the route service failed; give the model the reason rather than a bare HTTP error
        return {"error": response.json().get("detail", response.text)}
    response.raise_for_status()
    return response.json()


TOOL_SCHEMA = {
    "name": "generate_routes",
    "description": (
        "Returns the trip's 'fastest' and 'backroads' routes with distance, duration, climbing, a terrain-only "
        "scenic_score and duration_vs_fastest. If the trip already has both routes they are returned with "
        "reused: true; set force only when the user asks for new routes."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "trip_id": {"type": "integer"},
            "force": {"type": "boolean", "description": "Generate new routes even if the trip has them"},
        },
        "required": ["trip_id"],
        "additionalProperties": False,
    },
}
