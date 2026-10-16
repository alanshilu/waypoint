import requests
from app.agent.tools.geocode_location import BASE_URL


def generate_routes(trip_id: int) -> dict:
    """Generate route candidates for a trip."""
    response = requests.post(
        f"{BASE_URL}/routes/generate/{trip_id}",
        timeout=75,
    )
    response.raise_for_status()
    return response.json()


TOOL_SCHEMA = {
    "name": "generate_routes",
    "description": "Generates fastest and backroads route candidates with scenic scores.",
    "input_schema": {
        "type": "object",
        "properties": {"trip_id": {"type": "integer"}},
        "required": ["trip_id"],
    },
}
