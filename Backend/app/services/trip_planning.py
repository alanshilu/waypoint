"""
A route split into days of driving: each overnight stop and the destination, with arrival dates and the
forecast for that date, and a lunch stop per day. Positions are computed (stop_planning), never guessed.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from functools import lru_cache

from geoalchemy2.shape import to_shape

from app.models.route import Route
from app.models.trip import Trip
from app.services.providers import Geocoder, OpenMeteoWeather, OrsGeocoder, WeatherProvider
from app.services.stop_planning import lunch_stops, plan_stops

PLAN_NOTES = [
    "Driving time is spread along the route in proportion to distance (uniform pace).",
    "Arrival dates use the origin's UTC offset for the whole trip; time-zone crossings and DST changes are not applied.",
    "Overnight points are where each day's driving time runs out; names come from reverse geocoding, "
    "or 'near <lat>,<lon>' when that fails.",
    "forecast is null when the arrival date is more than 15 days away or the lookup fails.",
    "lunch_stops are where each day's driving reaches noon; the lunch break is not added to driving times.",
]


class TripPlanner:
    """Plans a route's days with the given geocoder (stop names) and weather (time zone, forecasts)."""

    def __init__(self, geocoder: Geocoder, weather: WeatherProvider):
        self.geocoder = geocoder
        self.weather = weather

    def plan(self, trip: Trip, route: Route, max_hours: float, start: datetime | None = None) -> dict:
        """start defaults to tomorrow 08:00 at the origin; a naive start is taken as the origin's local time."""
        origin = to_shape(trip.origin_point)
        notes = list(PLAN_NOTES)
        try:
            offset_s = self.weather.utc_offset_seconds(origin.y, origin.x)
        except Exception:  # noqa: BLE001 - fall back to UTC and say so
            offset_s = 0
            notes.append("The origin's time zone lookup failed; dates use UTC.")
        tz = timezone(timedelta(seconds=offset_s))

        if start is None:
            tomorrow = datetime.now(tz).date() + timedelta(days=1)
            start = datetime.combine(tomorrow, time(8, 0), tzinfo=tz)
        elif start.tzinfo is None:
            start = start.replace(tzinfo=tz)
        else:
            start = start.astimezone(tz)

        coords = list(to_shape(route.geometry).coords)
        stops = plan_stops(coords, route.duration_seconds, route.distance_miles, start, max_hours)
        for stop in stops:
            stop["id"] = f"{route.id}-{stop['day']}"
            if stop["kind"] == "destination":
                stop["name"] = trip.destination_name
            else:
                stop["name"] = self.geocoder.reverse_geocode(stop["lat"], stop["lon"])
            try:
                stop["forecast"] = self.weather.forecast_for_date(stop["lat"], stop["lon"], stop["arrival_date"])
            except Exception:  # noqa: BLE001 - a missing forecast must not lose the plan
                stop["forecast"] = None

        lunches = lunch_stops(coords, route.duration_seconds, route.distance_miles, start, max_hours)
        for lunch in lunches:
            lunch["id"] = f"{route.id}-{lunch['day']}-lunch"
            lunch["name"] = self.geocoder.reverse_geocode(lunch["lat"], lunch["lon"])

        return {
            "trip_id": trip.id,
            "route_id": route.id,
            "route_type": route.route_type,
            "start": start.isoformat(timespec="minutes"),
            "utc_offset_hours": offset_s / 3600,
            "max_drive_hours_per_day": max_hours,
            "days": len(stops),
            "stops": stops,
            "lunch_stops": lunches,
            "notes": notes,
        }


@lru_cache(maxsize=1)
def get_trip_planner() -> TripPlanner:
    """The app's planner, on OpenRouteService geocoding and Open-Meteo. The FastAPI dependency."""
    return TripPlanner(OrsGeocoder(), OpenMeteoWeather())
