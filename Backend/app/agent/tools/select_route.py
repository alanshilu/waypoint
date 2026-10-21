import requests
from app.agent.tools.geocode_location import BASE_URL
from app.agent.tools.http import check
from app.core.internal import internal_headers


def select_route(route_id: int) -> dict:
    """Mark a specific route as the trip's chosen route."""
    response = requests.post(
        f"{BASE_URL}/routes/select/{route_id}",
        headers=internal_headers(),
        timeout=10,
    )
    check(response)
    return response.json()


TOOL_SCHEMA = {
    "name": "select_route",
    "description": "Marks one of the generated routes as the user's chosen route.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {"route_id": {"type": "integer"}},
        "required": ["route_id"],
        "additionalProperties": False,
    },
}
