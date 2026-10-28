import requests

from app.agent.tools.geocode_location import BASE_URL
from app.agent.tools import http
from app.agent.tools.http import check


def get_weather_forecast(lat: float, lon: float, target_date: str | None = None) -> dict:
    """Gets the forecast for a location: one day when target_date is given, otherwise 7 days."""
    params: dict = {"lat": lat, "lon": lon}
    if target_date:
        params["target_date"] = target_date
    response = requests.get(f"{BASE_URL}/weather/forecast", params=params, headers=http.headers(),
                            timeout=http.timeout(20))
    if response.status_code == 400:
        return {"error": response.json().get("detail", response.text), "target_date": target_date}
    check(response)
    return response.json()


TOOL_SCHEMA = {
    "name": "get_weather_forecast",
    "description": (
        "Gets the weather forecast for a point. Set target_date to the day you will be there "
        "(the arrival_date from plan_stops); the forecast reaches at most 15 days ahead."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "lat": {"type": "number"},
            "lon": {"type": "number"},
            "target_date": {"type": "string", "format": "date", "description": "YYYY-MM-DD"},
        },
        "required": ["lat", "lon"],
        "additionalProperties": False,
    },
}
