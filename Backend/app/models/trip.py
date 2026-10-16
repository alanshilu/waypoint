
from datetime import datetime, timezone

from geoalchemy2 import Geometry
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from app.core.db import Base


class Trip(Base):
    __tablename__ = "trips"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=True)

    origin_name = Column(String, nullable=False)
    origin_point = Column(Geometry(geometry_type="POINT", srid=4326), nullable=False)

    destination_name = Column(String, nullable=False)
    destination_point = Column(Geometry(geometry_type="POINT", srid=4326), nullable=False)

    selected_route_id = Column(Integer, ForeignKey("routes.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


