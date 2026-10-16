# app/api/v1/trips.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from shapely.geometry import Point
from geoalchemy2.shape import from_shape
from app.core.db import get_db
from app.models.route import Route
from app.models.trip import Trip
from app.schemas.trip import TripCreate
from app.api.v1.serializers import DEFAULT_SIMPLIFY_TOLERANCE, trip_to_dict

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