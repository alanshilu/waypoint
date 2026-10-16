from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, JSON
from geoalchemy2 import Geometry
from datetime import datetime, timezone

from app.core.db import Base


class Route(Base):
    __tablename__ = "routes"

    id = Column(Integer, primary_key=True)
    trip_id = Column(Integer, ForeignKey("trips.id"), nullable=False)

    route_type = Column(String, nullable=False)
    distance_miles = Column(Float, nullable=False)
    duration_seconds = Column(Integer, nullable=False)
    geometry = Column(Geometry(geometry_type="LINESTRING", srid=4326), nullable=False)

    ascent_m = Column(Float, nullable=True)      # new
    descent_m = Column(Float, nullable=True)     # new
    scenic_score = Column(Float, nullable=True)  # optional -- store the computed score too

    # Downsampled [{"mile": float, "m": float}, ...]; null for routes saved before elevation was kept
    elevation_profile = Column(JSON, nullable=True)

    is_selected = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
