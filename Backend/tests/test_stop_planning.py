from datetime import datetime, timedelta, timezone

import pytest

from app.services.stop_planning import plan_stops

CENTRAL = timezone(timedelta(hours=-5))
START = datetime(2026, 10, 17, 8, 0, tzinfo=CENTRAL)
# A straight line along the equator in 10 equal one-degree segments
LINE = [[float(x), 0.0] for x in range(11)]


def test_splits_at_day_limits_with_uniform_pace():
    stops = plan_stops(LINE, total_duration_s=20 * 3600, total_miles=600, start=START, max_drive_hours_per_day=8)
    assert [s["day"] for s in stops] == [1, 2, 3]
    assert [s["kind"] for s in stops] == ["overnight", "overnight", "destination"]
    # 8 h and 16 h of a 20 h drive are 40% and 80% of the way
    assert stops[0]["lon"] == pytest.approx(4.0)
    assert stops[1]["lon"] == pytest.approx(8.0)
    assert stops[2]["lon"] == pytest.approx(10.0)
    assert [s["cumulative_miles"] for s in stops] == [240.0, 480.0, 600.0]
    assert [s["cumulative_drive_hours"] for s in stops] == [8.0, 16.0, 20.0]


def test_arrival_dates_advance_one_day_per_leg():
    stops = plan_stops(LINE, 20 * 3600, 600, START, 8)
    assert [s["arrival_date"] for s in stops] == ["2026-10-17", "2026-10-18", "2026-10-19"]
    # the last leg is 4 h, so the destination is reached at noon on day 3
    assert stops[-1]["arrival_time"] == "2026-10-19T12:00-05:00"


def test_exact_multiple_has_no_extra_overnight():
    stops = plan_stops(LINE, 16 * 3600, 600, START, 8)
    assert [s["kind"] for s in stops] == ["overnight", "destination"]
    assert stops[-1]["arrival_date"] == "2026-10-18"


def test_trip_under_one_day():
    stops = plan_stops(LINE, 5 * 3600, 300, START, 8)
    assert len(stops) == 1
    assert stops[0]["kind"] == "destination"
    assert stops[0]["arrival_date"] == "2026-10-17"
    assert stops[0]["cumulative_miles"] == 300.0


def test_late_start_arrives_after_midnight():
    late = datetime(2026, 10, 17, 20, 0, tzinfo=CENTRAL)
    stops = plan_stops(LINE, 10 * 3600, 600, late, 8)
    assert stops[0]["arrival_date"] == "2026-10-18"  # 20:00 + 8 h
    assert stops[1]["arrival_date"] == "2026-10-18"  # day 2 starts 20:00 on the 18th, 2 h left


def test_segment_durations_override_uniform_pace():
    line = [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]]
    # first segment takes 2 h, second 10 h: hour 8 is 60% into the second segment
    stops = plan_stops(line, 12 * 3600, 138, START, 8, segment_durations=[2 * 3600, 10 * 3600])
    assert stops[0]["lon"] == pytest.approx(1.6)
    assert stops[0]["cumulative_miles"] == pytest.approx(69 + 69 * 0.6, abs=0.1)


def test_rejects_bad_input():
    with pytest.raises(ValueError):
        plan_stops(LINE, 3600, 10, START, 0)
    with pytest.raises(ValueError):
        plan_stops([[0, 0]], 3600, 10, START)
    with pytest.raises(ValueError):
        plan_stops(LINE, 3600, 10, START, segment_durations=[1, 2])


# ---- lunch_stops ----

from app.services.stop_planning import lunch_stops  # noqa: E402


def test_lunch_is_where_the_clock_reads_noon_each_day():
    # 20 h at 8 h/day from 08:00: noon is 4 h into days 1 and 2 (20% and 60% of the way) and day 3
    # (4 h of driving, ending at noon) has no driving after noon, so no lunch point
    lunches = lunch_stops(LINE, 20 * 3600, 600, START, 8)
    assert [(lunch["day"], lunch["kind"]) for lunch in lunches] == [(1, "lunch"), (2, "lunch")]
    assert lunches[0]["lon"] == pytest.approx(2.0)
    assert lunches[1]["lon"] == pytest.approx(6.0)
    assert [lunch["cumulative_miles"] for lunch in lunches] == [120.0, 360.0]
    assert [lunch["time"] for lunch in lunches] == ["2026-10-17T12:00-05:00", "2026-10-18T12:00-05:00"]


def test_no_lunch_on_the_road_when_the_day_starts_after_noon_or_ends_by_it():
    afternoon = START.replace(hour=13)
    assert lunch_stops(LINE, 5 * 3600, 300, afternoon, 8) == []
    # 08:00 + 4 h 20 min of driving ends 12:20: under the 30 minutes of driving needed after noon
    assert lunch_stops(LINE, 4 * 3600 + 1200, 260, START, 8) == []
    # 08:00 + 5 h: an hour of driving after noon, so lunch at 80% of the way
    (lunch,) = lunch_stops(LINE, 5 * 3600, 300, START, 8)
    assert lunch["lon"] == pytest.approx(8.0)


def test_lunch_follows_the_same_pace_as_the_stops():
    # an 8 h day from 08:00 whose first half takes 2 h and second half 6 h
    durations = [2 * 3600 / 5] * 5 + [6 * 3600 / 5] * 5
    (lunch,) = lunch_stops(LINE, 8 * 3600, 600, START, 8, segment_durations=durations)
    # 4 h in: 2 h covered the first half, then 2 of the second half's 6 h, a third of the way along it
    assert lunch["lon"] == pytest.approx(5 + 5 / 3)
