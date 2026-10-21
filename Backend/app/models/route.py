from datetime import datetime, timezone

from geoalchemy2 import Geometry
from sqlalchemy import JSON, Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, Index, Integer, String, func

from app.core.db import Base


class Route(Base):
    __tablename__ = "routes"
    __table_args__ = (
        CheckConstraint("route_type IN ('fastest','backroads')", name="ck_routes_type"),
        CheckConstraint("distance_miles > 0", name="ck_routes_distance"),
        CheckConstraint("duration_seconds > 0", name="ck_routes_duration"),
    )

    id = Column(Integer, primary_key=True)
    # Deleting a trip deletes its routes
    trip_id = Column(Integer, ForeignKey("trips.id", name="routes_trip_id_fkey", ondelete="CASCADE"), nullable=False)

    route_type = Column(String, nullable=False)
    distance_miles = Column(Float, nullable=False)
    duration_seconds = Column(Integer, nullable=False)
    geometry = Column(Geometry(geometry_type="LINESTRING", srid=4326), nullable=False)

    ascent_m = Column(Float, nullable=True)      # new
    descent_m = Column(Float, nullable=True)     # new
    scenic_score = Column(Float, nullable=True)  # optional -- store the computed score too

    # Downsampled [{"mile": float, "m": float}, ...]; null for routes saved before elevation was kept
    elevation_profile = Column(JSON, nullable=True)
    # Turn-by-turn steps (routing_service.directions_from); null for routes saved before directions were kept
    directions = Column(JSON, nullable=True)

    is_selected = Column(Boolean, default=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )


# Serves "newest route of each type for a trip" (GET /trips/{id}, route reuse in /routes/generate)
Index("idx_routes_trip_type_created", Route.trip_id, Route.route_type, Route.created_at.desc())
