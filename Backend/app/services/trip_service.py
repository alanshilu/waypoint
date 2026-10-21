"""Creating a trip, or reusing a recent one with the same ends, so an agent retry doesn't make duplicates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Point
from sqlalchemy.orm import Session

from app.models.route import Route
from app.models.trip import Trip
from app.schemas.trip import TripCreate
from app.services.trip_matching import REUSE_WINDOW, recent_enough, same_trip


@dataclass
class TripResult:
    trip_id: int
    reused: bool


def find_recent_trip(db: Session, payload: TripCreate) -> Trip | None:
    """A trip from the last REUSE_WINDOW with the same origin and destination (within trip_matching's tolerance)."""
    since = datetime.now(timezone.utc) - REUSE_WINDOW
    wanted = ((payload.origin_lat, payload.origin_lon), (payload.destination_lat, payload.destination_lon))
    for trip in db.query(Trip).filter(Trip.created_at >= since).order_by(Trip.created_at.desc()):
        o, d = to_shape(trip.origin_point), to_shape(trip.destination_point)
        if recent_enough(trip.created_at) and same_trip(*wanted, (o.y, o.x), (d.y, d.x)):
            return trip
    return None


def create_trip(db: Session, payload: TripCreate, reuse_recent: bool = False) -> TripResult:
    if reuse_recent:
        recent = find_recent_trip(db, payload)
        if recent:
            return TripResult(recent.id, reused=True)

    # Shapely Points are (longitude, latitude)
    trip = Trip(
        name=payload.name,
        origin_name=payload.origin_name,
        origin_point=from_shape(Point(payload.origin_lon, payload.origin_lat), srid=4326),
        destination_name=payload.destination_name,
        destination_point=from_shape(Point(payload.destination_lon, payload.destination_lat), srid=4326),
    )
    db.add(trip)
    db.commit()
    db.refresh(trip)  # for the generated id
    return TripResult(trip.id, reused=False)


def routes_to_show(db: Session, trip: Trip) -> list[Route]:
    """
    The trip's routes as the app shows them: /routes/generate adds two rows per call, so the newest of each
    type, except that the selected route stands for its type. In id order.
    """
    routes = db.query(Route).filter(Route.trip_id == trip.id).order_by(Route.id.desc()).all()
    latest: dict[str, Route] = {}
    for route in routes:
        latest.setdefault(route.route_type, route)
    if trip.selected_route_id is not None:
        selected = next((r for r in routes if r.id == trip.selected_route_id), None)
        if selected:
            latest[selected.route_type] = selected
    return sorted(latest.values(), key=lambda r: r.id)
