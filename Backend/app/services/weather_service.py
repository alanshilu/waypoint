import openmeteo_requests
import requests_cache
from retry_requests import retry
from datetime import date, datetime, timezone
import math

cache_session = requests_cache.CachedSession('.cache', expire_after=3600)
retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
openmeteo = openmeteo_requests.Client(session=retry_session)

URL = "https://api.open-meteo.com/v1/forecast"

WEATHER_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
}

def describe_code(code):
    # Ensure code is treated as an int, handling potential NaN values
    if math.isnan(code):
        return "Unknown"
    return WEATHER_CODES.get(int(code), f"Unknown ({code})")

def get_current_weather(lat: float, lon: float, units: str = "fahrenheit") -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": ["temperature_2m", "wind_speed_10m", "weather_code"],
        "temperature_unit": units,
        "wind_speed_unit": "mph" if units == "fahrenheit" else "kmh",
        "timezone": "auto",
    }
    responses = openmeteo.weather_api(URL, params=params)
    current = responses[0].Current()

    return {
        "temp": round(float(current.Variables(0).Value()), 1),
        "wind_speed": round(float(current.Variables(1).Value()), 1),
        "condition": describe_code(current.Variables(2).Value()),
    }

def get_forecast(lat: float, lon: float, days: int = 7, units: str = "fahrenheit") -> list[dict]:
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": [
            "temperature_2m_max", "temperature_2m_min",
            "precipitation_probability_max", "weather_code",
        ],
        "temperature_unit": units,
        "timezone": "auto",
        "forecast_days": min(days, 16),
    }
    responses = openmeteo.weather_api(URL, params=params)
    daily = responses[0].Daily()

    temp_max = daily.Variables(0).ValuesAsNumpy()
    temp_min = daily.Variables(1).ValuesAsNumpy()
    precip_prob = daily.Variables(2).ValuesAsNumpy()
    weather_code = daily.Variables(3).ValuesAsNumpy()

    num_days = len(temp_max)
    start = daily.Time()
    interval = daily.Interval()

    forecast = []
    for i in range(num_days):
        day_timestamp = start + i * interval
        # FIX: Force UTC parsing to prevent day-shifting based on server timezone
        day_date = datetime.fromtimestamp(day_timestamp, tz=timezone.utc).date()
        
        # FIX: Cast numpy arrays to native python types for FastAPI JSON serialization
        forecast.append({
            "date": day_date.isoformat(),
            "temp_max": round(float(temp_max[i]), 1),
            "temp_min": round(float(temp_min[i]), 1),
            "precip_probability": int(precip_prob[i]) if not math.isnan(precip_prob[i]) else 0,
            "condition": describe_code(weather_code[i]),
        })
    return forecast

def get_utc_offset_seconds(lat: float, lon: float) -> int:
    """The current UTC offset at a point, from Open-Meteo's time zone lookup (cached like other calls)."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": ["weather_code"],
        "timezone": "auto",
        "forecast_days": 1,
    }
    responses = openmeteo.weather_api(URL, params=params)
    return int(responses[0].UtcOffsetSeconds())

def get_forecast_for_date(lat: float, lon: float, target_date, units: str = "fahrenheit") -> dict | None:
    # FIX: Accept strings from the API and convert them to date objects
    if isinstance(target_date, str):
        target_date = date.fromisoformat(target_date)

    days_ahead = (target_date - date.today()).days
    if days_ahead < 0 or days_ahead > 15: # Open-Meteo allows max 16 days total (0 to 15 days ahead)
        return None

    forecast = get_forecast(lat, lon, days=days_ahead + 1, units=units)
    match = [f for f in forecast if f["date"] == target_date.isoformat()]
    return match[0] if match else None