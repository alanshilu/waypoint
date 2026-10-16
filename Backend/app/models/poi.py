from sqlalchemy import Column, Integer, String, DateTime, UniqueConstraint
from geoalchemy2 import Geometry
from datetime import datetime, timezone
from app.core.db import Base


class POI(Base):
    __tablename__ = "pois"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_pois_source_external_id"),
    )

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False)
    location = Column(Geometry(geometry_type="POINT", srid=4326), nullable=False)

    source = Column(String, nullable=False)
    external_id = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
