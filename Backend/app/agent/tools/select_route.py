import requests
from app.agent.tools.geocode_location import BASE_URL
from app.agent.tools import http
from app.agent.tools.http import check


def select_route(route_id: int) -> dict:
    """Mark a specific route as the trip's chosen route."""
    response = requests.post(
        f"{BASE_URL}/routes/select/{route_id}",
        headers=http.headers(internal=True),
        timeout=http.timeout(10),
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
