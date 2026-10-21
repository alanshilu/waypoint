"""When Open-Meteo refuses (its free tier's daily limit is per IP), the National Weather Service stands in."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agent.tools.http import ToolCallError, check
from app.main import app
from app.services import nws, weather_service

LIMIT = RuntimeError("Daily API request limit exceeded. Please try again tomorrow.")

POINT = {"properties": {"timeZone": "America/Los_Angeles", "forecast": "https://api.weather.gov/gridpoints/LOX/155,45/forecast"}}
PERIODS = [
    {"startTime": "2026-10-21T18:00:00-07:00", "isDaytime": False, "temperature": 59, "temperatureUnit": "F",
     "probabilityOfPrecipitation": {"value": 94}, "shortForecast": "Showers And Thunderstorms"},
    {"startTime": "2026-10-22T06:00:00-07:00", "isDaytime": True, "temperature": 68, "temperatureUnit": "F",
     "probabilityOfPrecipitation": {"value": 40}, "shortForecast": "Chance Rain Showers"},
    {"startTime": "2026-10-22T18:00:00-07:00", "isDaytime": False, "temperature": 55, "temperatureUnit": "F",
     "probabilityOfPrecipitation": {"value": None}, "shortForecast": "Partly Cloudy"},
]


class FakeSession:
    """Answers the NWS points and forecast URLs; records what was asked and with which headers."""

    def __init__(self, point=POINT, periods=PERIODS, point_status=200):
        self.point, self.periods, self.point_status = point, periods, point_status
        self.asked = []

    def get(self, url, headers, timeout):
        self.asked.append((url, headers))
        if "/points/" in url:
            return SimpleNamespace(status_code=self.point_status, json=lambda: self.point)
        return SimpleNamespace(status_code=200, json=lambda: {"properties": {"periods": self.periods}})


def test_nws_periods_fold_into_days_in_the_local_time_zone():
    session = FakeSession()
    days, offset = nws.daily_forecast(session, 34.05, -118.24)
    assert days == [
        # only the evening is left of the 21st: that period describes it
        {"date": "2026-10-21", "temp_max": 59.0, "temp_min": 59.0, "precip_probability": 94,
         "condition": "Showers And Thunderstorms"},
        # the day's high and description from the daytime period, the low from the night
        {"date": "2026-10-22", "temp_max": 68.0, "temp_min": 55.0, "precip_probability": 40,
         "condition": "Chance Rain Showers"},
    ]
    assert offset == -7 * 3600
    assert session.asked[0][0] == "https://api.weather.gov/points/34.0500,-118.2400"
    assert session.asked[0][1]["User-Agent"].startswith("Waypoint")  # NWS asks every client to identify itself


def test_nws_in_celsius():
    days, _ = nws.daily_forecast(FakeSession(), 34.05, -118.24, units="celsius")
    assert days[1]["temp_max"] == 20.0 and days[1]["temp_min"] == 12.8


def test_nws_outside_the_us_says_so():
    with pytest.raises(nws.NwsError, match="covers the US only"):
        nws.daily_forecast(FakeSession(point_status=404), 51.5, -0.12)


def test_open_meteo_refusing_falls_back_to_the_nws(monkeypatch):
    def refused(*args):
        raise LIMIT

    monkeypatch.setattr(weather_service, "_open_meteo_forecast", refused)
    monkeypatch.setattr(weather_service, "_open_meteo_utc_offset", refused)
    monkeypatch.setattr(weather_service, "retry_session", FakeSession())
    forecast = weather_service.get_forecast(34.05, -118.24, days=1)
    assert forecast == [{"date": "2026-10-21", "temp_max": 59.0, "temp_min": 59.0, "precip_probability": 94,
                         "condition": "Showers And Thunderstorms"}]
    assert weather_service.get_utc_offset_seconds(34.05, -118.24) == -7 * 3600


def test_open_meteo_answering_never_asks_the_nws(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(weather_service, "_open_meteo_forecast", lambda *a: [{"date": "2026-10-21"}])
    monkeypatch.setattr(weather_service, "retry_session", session)
    assert weather_service.get_forecast(34.05, -118.24) == [{"date": "2026-10-21"}]
    assert session.asked == []


def test_both_failing_is_a_502_with_both_reasons(monkeypatch):
    def refused(*args):
        raise LIMIT

    monkeypatch.setattr(weather_service, "_open_meteo_forecast", refused)
    monkeypatch.setattr(weather_service, "retry_session", FakeSession(point_status=404))
    r = TestClient(app).get("/weather/forecast", params={"lat": 51.5, "lon": -0.12})
    assert r.status_code == 502
    assert r.json()["detail"] == ("Open-Meteo: Daily API request limit exceeded. Please try again tomorrow.; "
                                  "National Weather Service: no forecast for this point "
                                  "(the National Weather Service covers the US only)")


def test_a_tool_error_carries_the_apis_reason():
    response = SimpleNamespace(status_code=502, json=lambda: {"detail": "Open-Meteo: Daily API request limit exceeded"},
                               text="", request=SimpleNamespace(path_url="/weather/forecast?lat=1&lon=2"))
    with pytest.raises(ToolCallError) as caught:
        check(response)
    assert str(caught.value) == "/weather/forecast answered HTTP 502: Open-Meteo: Daily API request limit exceeded"
    check(SimpleNamespace(status_code=200))  # a success passes
