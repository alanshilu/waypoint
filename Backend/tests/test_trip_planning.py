"""TripPlanner with its geocoder and weather passed in, and which routes a trip shows."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from geoalchemy2.shape import from_shape
from shapely.geometry import LineString, Point

from app.services.trip_planning import TripPlanner
from app.services.trip_service import routes_to_show

# San Francisco to Los Angeles as a straight line: 8 h at 8 h a day is one day, 12 h is two
TRIP = SimpleNamespace(id=1, destination_name="Los Angeles, CA",
                       origin_point=from_shape(Point(-122.42, 37.77), srid=4326))
COORDS = [(-122.42, 37.77), (-120.3, 35.9), (-118.24, 34.05)]


def route(duration_hours: float):
    return SimpleNamespace(id=7, route_type="fastest", duration_seconds=int(duration_hours * 3600), distance_miles=382.0,
                           geometry=from_shape(LineString(COORDS), srid=4326))


class Geocoder:
    def __init__(self):
        self.asked = []

    def reverse_geocode(self, lat, lon):
        self.asked.append((round(lat, 1), round(lon, 1)))
        return f"Town {len(self.asked)}"


class Weather:
    def __init__(self, offset_s=-7 * 3600, offset_error=None, forecast_error=None):
        self.offset_s, self.offset_error, self.forecast_error = offset_s, offset_error, forecast_error

    def utc_offset_seconds(self, lat, lon):
        if self.offset_error:
            raise self.offset_error
        return self.offset_s

    def forecast_for_date(self, lat, lon, day):
        if self.forecast_error:
            raise self.forecast_error
        return {"date": str(day), "condition": "Clear sky"}


START = datetime(2026, 10, 22, 8, 0)


def test_a_two_day_route_names_its_stops_with_the_geocoder_and_forecasts_each_arrival():
    geocoder = Geocoder()
    plan = TripPlanner(geocoder, Weather()).plan(TRIP, route(12), max_hours=8, start=START)
    overnight, destination = plan["stops"]
    assert plan["days"] == 2 and plan["start"] == "2026-10-22T08:00-07:00"  # a naive start is the origin's local time
    assert (overnight["id"], overnight["kind"], overnight["name"]) == ("7-1", "overnight", "Town 1")
    assert (destination["id"], destination["name"]) == ("7-2", "Los Angeles, CA")  # the trip's own name, not geocoded
    assert destination["forecast"] == {"date": destination["arrival_date"], "condition": "Clear sky"}
    # day 2 is 08:00-12:00: no driving left after noon, so only day 1 has a lunch stop
    assert [lunch["id"] for lunch in plan["lunch_stops"]] == ["7-1-lunch"]
    assert len(geocoder.asked) == 2  # the overnight stop and the lunch


def test_a_failed_time_zone_lookup_plans_in_utc_and_says_so():
    plan = TripPlanner(Geocoder(), Weather(offset_error=RuntimeError("timeout"))).plan(TRIP, route(6), 8, START)
    assert plan["utc_offset_hours"] == 0 and plan["start"].endswith("+00:00")
    assert "The origin's time zone lookup failed; dates use UTC." in plan["notes"]


def test_a_failed_forecast_keeps_the_plan():
    plan = TripPlanner(Geocoder(), Weather(forecast_error=RuntimeError("503"))).plan(TRIP, route(12), 8, START)
    assert [s["forecast"] for s in plan["stops"]] == [None, None] and plan["days"] == 2


def test_without_a_start_the_trip_leaves_tomorrow_at_eight_local_time():
    plan = TripPlanner(Geocoder(), Weather()).plan(TRIP, route(6), 8)
    tomorrow = (datetime.now(timezone(timedelta(hours=-7))).date() + timedelta(days=1)).isoformat()
    assert plan["start"] == f"{tomorrow}T08:00-07:00"
    assert date.fromisoformat(plan["stops"][0]["arrival_date"]) == date.fromisoformat(tomorrow)


def test_a_trip_shows_the_newest_route_of_each_type_unless_one_is_selected():
    rows = [SimpleNamespace(id=i, route_type=t) for i, t in ((4, "backroads"), (3, "fastest"), (2, "backroads"), (1, "fastest"))]
    db = SimpleNamespace(query=lambda model: SimpleNamespace(
        filter=lambda *a: SimpleNamespace(order_by=lambda *a: SimpleNamespace(all=lambda: rows))))
    newest = routes_to_show(db, SimpleNamespace(id=1, selected_route_id=None))
    assert [r.id for r in newest] == [3, 4]
    picked_older = routes_to_show(db, SimpleNamespace(id=1, selected_route_id=1))
    assert [r.id for r in picked_older] == [1, 4]
