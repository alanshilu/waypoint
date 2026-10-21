"""
Forecasts from the US National Weather Service (api.weather.gov): free, no key and no daily quota, so it
stands in when Open-Meteo's free tier refuses (its daily limit is per IP address, and hosting platforms
share outbound addresses). US locations only, about 7 days ahead, in day and night periods that are
folded here into the same daily shape Open-Meteo gives: {date, temp_max, temp_min, precip_probability,
condition}, dates in the location's time zone.
"""

from __future__ import annotations

from datetime import datetime

# NWS asks every client to identify itself
USER_AGENT = "Waypoint road-trip planner (https://github.com/alanshilu/waypoint)"
POINTS_URL = "https://api.weather.gov/points/{lat:.4f},{lon:.4f}"
TIMEOUT_S = 15


class NwsError(Exception):
    """No NWS forecast for the point: outside the US, or the service failed."""


def _get(session, url: str) -> dict:
    response = session.get(url, headers={"User-Agent": USER_AGENT, "Accept": "application/geo+json"}, timeout=TIMEOUT_S)
    if response.status_code == 404:
        raise NwsError("no forecast for this point (the National Weather Service covers the US only)")
    if response.status_code >= 400:
        raise NwsError(f"HTTP {response.status_code}")
    return response.json()


def _to_celsius(f: float) -> float:
    return (f - 32) * 5 / 9


def daily_forecast(session, lat: float, lon: float, units: str = "fahrenheit") -> tuple[list[dict], int]:
    """(days, utc_offset_s): the forecast by local date, and the location's current UTC offset. Raises NwsError."""
    point = _get(session, POINTS_URL.format(lat=lat, lon=lon))["properties"]
    periods = _get(session, point["forecast"])["properties"]["periods"]
    if not periods:
        raise NwsError("the forecast came back empty")

    by_date: dict[str, list[dict]] = {}
    for period in periods:
        by_date.setdefault(period["startTime"][:10], []).append(period)

    days = []
    for day, parts in by_date.items():
        temps = [p["temperature"] if p.get("temperatureUnit", "F") == "F" else p["temperature"] * 9 / 5 + 32
                 for p in parts]
        if units != "fahrenheit":
            temps = [_to_celsius(t) for t in temps]
        rain = [(p.get("probabilityOfPrecipitation") or {}).get("value") or 0 for p in parts]
        # the daytime period describes the day; a date with only an evening (tonight) uses that
        describing = next((p for p in parts if p.get("isDaytime")), parts[0])
        days.append({
            "date": day,
            "temp_max": round(float(max(temps)), 1),
            "temp_min": round(float(min(temps)), 1),
            "precip_probability": int(max(rain)),
            "condition": describing["shortForecast"],
        })

    offset = datetime.fromisoformat(periods[0]["startTime"]).utcoffset()
    return days, int(offset.total_seconds()) if offset else 0
