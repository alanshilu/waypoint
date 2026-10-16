"""get_forecast_for_date across the server/location date boundary, with Open-Meteo stubbed."""

from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.api.v1.endpoints import weather as weather_endpoint
from app.main import app
from app.services import weather_service


def stub_forecast(first_day: date):
    """Open-Meteo answering in the location's time zone, whose 'today' is first_day."""
    asked = {}

    def get_forecast(lat, lon, days=7, units="fahrenheit"):
        asked["days"] = days
        return [{"date": (first_day + timedelta(days=i)).isoformat(), "temp_max": 70.0 + i, "temp_min": 50.0,
                 "precip_probability": 0, "condition": "Clear sky"} for i in range(days)]

    return get_forecast, asked


def test_location_a_day_behind_the_server(monkeypatch):
    # The server is already on "today"; in Los Angeles it is still yesterday
    today = date.today()
    fake, asked = stub_forecast(today - timedelta(days=1))
    monkeypatch.setattr(weather_service, "get_forecast", fake)
    result = weather_service.get_forecast_for_date(34.05, -118.24, today.isoformat())
    assert result is not None and result["date"] == today.isoformat()
    assert asked["days"] == 2


def test_location_a_day_ahead_of_the_server(monkeypatch):
    today = date.today()
    fake, _ = stub_forecast(today + timedelta(days=1))
    monkeypatch.setattr(weather_service, "get_forecast", fake)
    yesterday_here = today + timedelta(days=1)
    assert weather_service.get_forecast_for_date(-33.9, 151.2, yesterday_here.isoformat())["date"] == yesterday_here.isoformat()


def test_out_of_range_dates_return_none(monkeypatch):
    fake, _ = stub_forecast(date.today())
    monkeypatch.setattr(weather_service, "get_forecast", fake)
    assert weather_service.get_forecast_for_date(0, 0, (date.today() - timedelta(days=2)).isoformat()) is None
    assert weather_service.get_forecast_for_date(0, 0, (date.today() + timedelta(days=16)).isoformat()) is None


def test_endpoint_returns_400_not_500_for_an_unavailable_date(monkeypatch):
    monkeypatch.setattr(weather_endpoint, "get_forecast_for_date", lambda *a, **k: None)
    r = TestClient(app).get("/weather/forecast", params={"lat": 0, "lon": 0, "target_date": "2030-01-01"})
    assert r.status_code == 400
    assert r.json()["detail"].startswith("Date is in the past")
