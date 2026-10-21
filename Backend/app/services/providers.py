"""
The outside services trip planning and route generation depend on, as small contracts, with the app's
implementations (OpenRouteService, Open-Meteo). Services take these as constructor arguments, so they can
be swapped (another router, a fake in a test) without touching the services.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from app.services import geocoding_service, routing_service, weather_service


class RoutingProvider(Protocol):
    def get_route_options(self, start_lon: float, start_lat: float, end_lon: float, end_lat: float) -> dict:
        """{"fastest": route, "backroads": route}, each with distance, duration, climb, geometry, directions.
        Raises routing_service.RoutingError when the router can't answer."""
        ...


class Geocoder(Protocol):
    def reverse_geocode(self, lat: float, lon: float) -> str:
        """A place name for the point ("near <lat>,<lon>" when there's none)."""
        ...


class WeatherProvider(Protocol):
    def utc_offset_seconds(self, lat: float, lon: float) -> int:
        ...

    def forecast_for_date(self, lat: float, lon: float, day: date | str) -> dict | None:
        ...


class OrsRouting:
    def get_route_options(self, start_lon, start_lat, end_lon, end_lat):
        return routing_service.get_route_options(start_lon, start_lat, end_lon, end_lat)


class OrsGeocoder:
    def reverse_geocode(self, lat, lon):
        return geocoding_service.reverse_geocode(lat, lon)


class OpenMeteoWeather:
    def utc_offset_seconds(self, lat, lon):
        return weather_service.get_utc_offset_seconds(lat, lon)

    def forecast_for_date(self, lat, lon, day):
        return weather_service.get_forecast_for_date(lat, lon, day)
