import requests
from app.agent.tools.geocode_location import BASE_URL


def get_weather_forecast(lat: float, lon: float) -> dict:
    """Get the multi-day weather forecast for a location."""
    response = requests.get(
        f"{BASE_URL}/weather/forecast",
        params={"lat": lat, "lon": lon},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


TOOL_SCHEMA = {
    "name": "get_weather_forecast",
    "description": "Gets the weather forecast for a location.",
    "input_schema": {
        "type": "object",
        "properties": {
            "lat": {"type": "number"},
            "lon": {"type": "number"},
        },
        "required": ["lat", "lon"],
    },
}
