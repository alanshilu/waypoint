
from datetime import datetime, timezone

from geoalchemy2 import Geometry
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func

from app.core.db import Base


class Trip(Base):
    __tablename__ = "trips"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=True)

    origin_name = Column(String, nullable=False)
    origin_point = Column(Geometry(geometry_type="POINT", srid=4326), nullable=False)

    destination_name = Column(String, nullable=False)
    destination_point = Column(Geometry(geometry_type="POINT", srid=4326), nullable=False)

    # trips and routes reference each other; use_alter adds this key after both tables exist.
    # Deleting the selected route clears the selection instead of failing.
    selected_route_id = Column(
        Integer,
        ForeignKey("routes.id", name="trips_selected_route_id_fkey", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
