import requests

from app.agent.tools.geocode_location import BASE_URL
from app.agent.tools import http
from app.agent.tools.http import check


def plan_stops(trip_id: int, route_id: int, start: str | None = None, max_hours: float | None = None) -> dict:
    """Splits a route into driving days and returns overnight stops with arrival dates and forecasts."""
    params: dict = {"route_id": route_id}
    if start:
        params["start"] = start
    if max_hours:
        params["max_hours"] = max_hours
    response = requests.post(f"{BASE_URL}/trips/{trip_id}/plan", params=params, headers=http.headers(),
                             # each stop is named by the geocoder, which retries a failing request
                             timeout=http.timeout(180))
    if response.status_code in (400, 404, 422):
        return {"error": response.json().get("detail", response.text)}
    check(response)
    return response.json()


TOOL_SCHEMA = {
    "name": "plan_stops",
    "description": (
        "Splits one of the trip's routes into driving days of at most max_hours each. Returns every overnight stop "
        "and the destination with a stable id, a reverse-geocoded name, cumulative miles and driving hours, the "
        "arrival_date, and the forecast for that arrival date (null when unavailable), plus lunch_stops: where "
        "each day's driving reaches noon, with an id and a name. Use it for multi-day drives, "
        "for any question about where to stop or stay, and before saying anything about weather on the trip."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "trip_id": {"type": "integer"},
            "route_id": {"type": "integer", "description": "A route id from generate_routes for this trip"},
            "start": {
                "type": "string",
                "format": "date-time",
                "description": "Departure, ISO 8601. Omit to use tomorrow 08:00 at the origin.",
            },
            "max_hours": {"type": "number", "description": "Maximum driving hours per day (default 8, at most 16)"},
        },
        "required": ["trip_id", "route_id"],
        "additionalProperties": False,
    },
}
