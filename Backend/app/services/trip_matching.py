"""Deciding when a new trip request is the same as an existing trip."""

from datetime import datetime, timedelta, timezone

# 3 decimal places of a degree is about 100 m: two geocodes of the same city land inside it
COORDINATE_PLACES = 3
REUSE_WINDOW = timedelta(hours=24)


def place_key(lat: float, lon: float) -> tuple[float, float]:
    return round(lat, COORDINATE_PLACES), round(lon, COORDINATE_PLACES)


def same_trip(origin_a, destination_a, origin_b, destination_b) -> bool:
    """Each argument is (lat, lon). True when both ends match after rounding; direction matters."""
    return place_key(*origin_a) == place_key(*origin_b) and place_key(*destination_a) == place_key(*destination_b)


def recent_enough(created_at: datetime | None, now: datetime | None = None) -> bool:
    if created_at is None:
        return False
    now = now or datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return now - created_at <= REUSE_WINDOW
