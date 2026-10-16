# app/api/v1/trips.py
from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Point
from sqlalchemy.orm import Session

from app.api.v1.serializers import DEFAULT_SIMPLIFY_TOLERANCE, trip_to_dict
from app.core.db import get_db
from app.models.route import Route
from app.models.trip import Trip
from app.schemas.trip import TripCreate
from app.services.geocoding_service import reverse_geocode
from app.services.stop_planning import plan_stops
from app.services.weather_service import get_forecast_for_date, get_utc_offset_seconds

router = APIRouter()

@router.post("/")
def create_trip(payload: TripCreate, db: Session = Depends(get_db)):

    # 1. Convert flat coordinates into PostGIS Geometry Points
    # Note: Shapely Points are defined as (longitude, latitude)
    origin_point_geom = from_shape(Point(payload.origin_lon, payload.origin_lat), srid=4326)
    dest_point_geom = from_shape(Point(payload.destination_lon, payload.destination_lat), srid=4326)

    # 2. Create the Database Record
    new_trip = Trip(
        name=payload.name,
        origin_name=payload.origin_name,
        origin_point=origin_point_geom,
        destination_name=payload.destination_name,
        destination_point=dest_point_geom
    )

    # 3. Save to PostgreSQL
    db.add(new_trip)
    db.commit()
    
    # 4. Refresh to get the auto-generated trip_id
    db.refresh(new_trip)

    # 5. Return the newly minted trip_id to the frontend
    return {
        "status": "success",
        "message": "Trip created successfully",
        "trip_id": new_trip.id
    }
@router.get("/trips")
def list_trips(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    # Fetches a limited number of trips, ordered by newest first
    trips = db.query(Trip).order_by(Trip.created_at.desc()).offset(skip).limit(limit).all()
    
    return {
        "status": "success",
        "trips": [
            {
                "id": t.id,
                "origin_name": t.origin_name,
                "destination_name": t.destination_name,
                "created_at": t.created_at
            } for t in trips
        ]
    }

@router.get("/{trip_id}")
def get_trip(
    trip_id: int,
    tolerance: float = Query(DEFAULT_SIMPLIFY_TOLERANCE, ge=0, description="Route simplification in degrees. 0 returns every point."),
    db: Session = Depends(get_db),
):
    """
    Returns a saved trip with its origin, destination and routes.
    """
    trip = db.query(Trip).filter(Trip.id == trip_id).first()

    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    # /routes/generate adds two rows per call, so keep only the newest of each type
    routes = db.query(Route).filter(Route.trip_id == trip_id).order_by(Route.id.desc()).all()
    latest = {}
    for route in routes:
        latest.setdefault(route.route_type, route)
    if trip.selected_route_id is not None:
        selected = next((r for r in routes if r.id == trip.selected_route_id), None)
        if selected:
            latest[selected.route_type] = selected

    return trip_to_dict(trip, sorted(latest.values(), key=lambda r: r.id), tolerance)


PLAN_NOTES = [
    "Driving time is spread along the route in proportion to distance (uniform pace).",
    "Arrival dates use the origin's UTC offset for the whole trip; time-zone crossings and DST changes are not applied.",
    "Overnight points are where each day's driving time runs out; names come from reverse geocoding, "
    "or 'near <lat>,<lon>' when that fails.",
    "forecast is null when the arrival date is more than 15 days away or the lookup fails.",
]


@router.post("/{trip_id}/plan")
def plan_trip_stops(
    trip_id: int,
    route_id: int = Query(..., description="One of this trip's routes"),
    max_hours: float = Query(8, gt=0, le=16, description="Maximum driving hours per day"),
    start: datetime | None = Query(None, description="Departure, ISO 8601. Default: tomorrow 08:00 at the origin."),
    db: Session = Depends(get_db),
):
    """
    Splits a route into days of at most max_hours of driving and returns each
    overnight stop and the destination with its arrival date and the forecast
    for that date. Stop positions are computed, never guessed; see notes.
    """
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")
    route = db.query(Route).filter(Route.id == route_id, Route.trip_id == trip_id).first()
    if not route:
        raise HTTPException(status_code=404, detail="Route not found for this trip")

    origin = to_shape(trip.origin_point)
    notes = list(PLAN_NOTES)
    try:
        offset_s = get_utc_offset_seconds(origin.y, origin.x)
    except Exception:  # noqa: BLE001 - fall back to UTC and say so
        offset_s = 0
        notes.append("The origin's time zone lookup failed; dates use UTC.")
    tz = timezone(timedelta(seconds=offset_s))

    if start is None:
        tomorrow = datetime.now(tz).date() + timedelta(days=1)
        start = datetime.combine(tomorrow, time(8, 0), tzinfo=tz)
    elif start.tzinfo is None:
        start = start.replace(tzinfo=tz)
    else:
        start = start.astimezone(tz)

    coords = list(to_shape(route.geometry).coords)
    stops = plan_stops(coords, route.duration_seconds, route.distance_miles, start, max_hours)

    for stop in stops:
        stop["id"] = f"{route.id}-{stop['day']}"
        if stop["kind"] == "destination":
            stop["name"] = trip.destination_name
        else:
            stop["name"] = reverse_geocode(stop["lat"], stop["lon"])
        try:
            stop["forecast"] = get_forecast_for_date(stop["lat"], stop["lon"], stop["arrival_date"])
        except Exception:  # noqa: BLE001 - a missing forecast must not lose the plan
            stop["forecast"] = None

    return {
        "trip_id": trip.id,
        "route_id": route.id,
        "route_type": route.route_type,
        "start": start.isoformat(timespec="minutes"),
        "utc_offset_hours": offset_s / 3600,
        "max_drive_hours_per_day": max_hours,
        "days": len(stops),
        "stops": stops,
        "notes": notes,
    }