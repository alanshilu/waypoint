from datetime import datetime, timedelta, timezone

from app.services.trip_matching import recent_enough, same_trip

SF = (37.778008, -122.431272)
LA = (34.053691, -118.242766)


def test_same_ends_after_rounding_match():
    assert same_trip(SF, LA, (37.77804, -122.43131), (34.05372, -118.24279))


def test_different_or_reversed_ends_do_not_match():
    assert not same_trip(SF, LA, LA, SF)
    assert not same_trip(SF, LA, SF, (34.06, -118.24))


def test_reuse_window_is_24_hours():
    now = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
    assert recent_enough(now - timedelta(hours=23, minutes=59), now)
    assert not recent_enough(now - timedelta(hours=24, minutes=1), now)
    assert not recent_enough(None, now)
    # naive timestamps are treated as UTC
    assert recent_enough(datetime(2026, 10, 16, 1), now)
