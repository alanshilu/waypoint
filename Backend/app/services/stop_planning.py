"""
Deterministic day-by-day stop planning along a route.

plan_stops walks the route geometry by cumulative driving time and splits it
into days of at most max_drive_hours_per_day. Each day ends at an overnight
stop; the last day ends at the destination. Nothing here calls an external
service or a model, so the same inputs always give the same stops.

Limitations (documented, deliberate):
- Stored routes only have a total duration, so unless segment_durations is
  given, driving time is spread over the line in proportion to distance
  (uniform pace). Real pace varies between highways and towns.
- Each day starts at the same local clock time as `start`. Arrival dates use
  the time zone of `start` (the origin's) for the whole trip; crossing a time
  zone or a DST change is not applied.
- Overnight points are where the drive time runs out, not snapped to towns;
  callers name them by reverse geocoding.
- Lunch points (lunch_stops) are where the clock reads noon on each day whose
  drive spans it; the lunch break itself is not added to the day's driving time.
"""

from __future__ import annotations

import math
from datetime import datetime, time, timedelta

EARTH_RADIUS_MILES = 3958.8


def _haversine_miles(a, b) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(min(1.0, h)))


def _drive_model(coords, total_duration_s, total_miles, segment_durations=None):
    """
    (total driving seconds, point_at, total miles): point_at(seconds) gives (lon, lat, miles) after
    that much driving, with time spread by segment_durations or in proportion to distance.
    """
    if len(coords) < 2:
        raise ValueError("a route needs at least two coordinates")
    if total_duration_s <= 0:
        raise ValueError("total_duration_s must be positive")

    lengths = [_haversine_miles(a, b) for a, b in zip(coords, coords[1:], strict=False)]
    measured = sum(lengths)
    mile_scale = (total_miles / measured) if measured > 0 and total_miles > 0 else 1.0

    if segment_durations is not None:
        if len(segment_durations) != len(lengths):
            raise ValueError("segment_durations needs one value per segment")
        durations = [max(0.0, float(d)) for d in segment_durations]
    elif measured > 0:
        durations = [total_duration_s * length / measured for length in lengths]
    else:
        durations = [total_duration_s / len(lengths)] * len(lengths)

    def point_at(target_s: float):
        elapsed, miles = 0.0, 0.0
        for (a, b), seg_s, seg_mi in zip(zip(coords, coords[1:], strict=False), durations, lengths, strict=False):
            if elapsed + seg_s >= target_s and seg_s > 0:
                t = (target_s - elapsed) / seg_s
                return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, (miles + seg_mi * t) * mile_scale
            elapsed += seg_s
            miles += seg_mi
        last = coords[-1]
        return last[0], last[1], measured * mile_scale

    return sum(durations), point_at, measured * mile_scale


def _days(total_time: float, day_limit: float) -> int:
    # A trip that ends exactly on a day boundary arrives that day; no extra overnight.
    return max(1, math.ceil(round(total_time / day_limit, 9)))


def plan_stops(
    coords: list,
    total_duration_s: float,
    total_miles: float,
    start: datetime,
    max_drive_hours_per_day: float = 8.0,
    segment_durations: list[float] | None = None,
) -> list[dict]:
    """
    coords: the route's LineString coordinates, [lon, lat] pairs (extra values ignored).
    total_duration_s: the route's driving time in seconds.
    total_miles: the route's distance; per-segment miles are scaled to add up to it.
    start: departure date and time, in the origin's time zone.
    segment_durations: optional seconds per segment (len(coords) - 1 values); overrides uniform pace.

    Returns one dict per day: {day, kind, lat, lon, cumulative_miles,
    cumulative_drive_hours, arrival_date, arrival_time}. kind is "overnight" for
    every day but the last, which is "destination".
    """
    if max_drive_hours_per_day <= 0:
        raise ValueError("max_drive_hours_per_day must be positive")
    total_time, point_at, total_route_miles = _drive_model(coords, total_duration_s, total_miles, segment_durations)
    day_limit = max_drive_hours_per_day * 3600
    days = _days(total_time, day_limit)

    stops = []
    for day in range(1, days + 1):
        is_last = day == days
        driven_s = total_time if is_last else day * day_limit
        lon, lat, miles = point_at(driven_s)
        if is_last:
            lon, lat, miles = coords[-1][0], coords[-1][1], total_route_miles
        today_s = driven_s - (day - 1) * day_limit
        arrival = start + timedelta(days=day - 1, seconds=today_s)
        stops.append({
            "day": day,
            "kind": "destination" if is_last else "overnight",
            "lat": round(lat, 5),
            "lon": round(lon, 5),
            "cumulative_miles": round(miles, 1),
            "cumulative_drive_hours": round(driven_s / 3600, 2),
            "arrival_date": arrival.date().isoformat(),
            "arrival_time": arrival.isoformat(timespec="minutes"),
        })
    return stops


def lunch_stops(
    coords: list,
    total_duration_s: float,
    total_miles: float,
    start: datetime,
    max_drive_hours_per_day: float = 8.0,
    segment_durations: list[float] | None = None,
    lunch_at: time = time(12, 0),
    min_drive_after_s: float = 1800,
) -> list[dict]:
    """
    One lunch point per day whose driving is underway at lunch_at (local to start) and continues
    at least min_drive_after_s afterwards; on other days lunch is at the day's start or end, so
    there is no point on the road for it. Days and pace match plan_stops.

    Returns [{day, kind: "lunch", lat, lon, cumulative_miles, time}].
    """
    total_time, point_at, _ = _drive_model(coords, total_duration_s, total_miles, segment_durations)
    day_limit = max_drive_hours_per_day * 3600
    days = _days(total_time, day_limit)
    lunches = []
    for day in range(1, days + 1):
        day_start = start + timedelta(days=day - 1)
        today_s = min(day_limit, total_time - (day - 1) * day_limit)
        noon = datetime.combine(day_start.date(), lunch_at, tzinfo=start.tzinfo)
        into_day_s = (noon - day_start).total_seconds()
        if into_day_s <= 0 or into_day_s + min_drive_after_s > today_s:
            continue
        lon, lat, miles = point_at((day - 1) * day_limit + into_day_s)
        lunches.append({
            "day": day,
            "kind": "lunch",
            "lat": round(lat, 5),
            "lon": round(lon, 5),
            "cumulative_miles": round(miles, 1),
            "time": noon.isoformat(timespec="minutes"),
        })
    return lunches
