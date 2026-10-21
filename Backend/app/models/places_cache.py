from sqlalchemy import Column, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB

from app.core.db import Base


class PlacesCacheEntry(Base):
    """One find_places search result, so the day-long cache survives restarts (see app/services/places/cache.py)."""

    __tablename__ = "places_cache"

    # "<kind>:<lat>:<lon>", the coordinates rounded to 2 decimals (about 1 km)
    key = Column(String, primary_key=True)
    # {"places", "source", "radius_km", "note"?}
    result = Column(JSONB, nullable=False)
    saved_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
