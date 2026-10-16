import requests
from app.agent.tools.geocode_location import BASE_URL


def select_route(route_id: int) -> dict:
    """Mark a specific route as the trip's chosen route."""
    response = requests.post(
        f"{BASE_URL}/routes/select/{route_id}",
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


TOOL_SCHEMA = {
    "name": "select_route",
    "description": "Marks one of the generated routes as the user's chosen route.",
    "input_schema": {
        "type": "object",
        "properties": {"route_id": {"type": "integer"}},
        "required": ["route_id"],
    },
}
