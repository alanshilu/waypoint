"""
GET /shared/{public_id}: a trip opened from its share link (/t/<public_id>), read-only.

Public, also with PUBLIC_DEMO=true, and costs nothing to serve: no agent, no outside service, one read. It
returns only what app/services/sharing.py puts in a shared trip, and is rate limited per client address
(SHARED_RATE_LIMIT_PER_MINUTE).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.rate_limit import SlidingWindowLimit
from app.services import sharing, trip_service

router = APIRouter()

_limit = SlidingWindowLimit(settings.shared_rate_limit_per_minute, 60)


def get_shared_limit() -> SlidingWindowLimit:
    """FastAPI dependency; tests override it."""
    return _limit


NOT_FOUND = "Shared trip not found"


@router.get("/{public_id}")
def get_shared_trip(public_id: str, request: Request, db: Session = Depends(get_db),
                    limit: SlidingWindowLimit = Depends(get_shared_limit)):
    # Behind a reverse proxy, run uvicorn with --proxy-headers so this is the visitor's address
    client_ip = request.client.host if request.client else "unknown"
    allowed, retry_after = limit.allow(client_ip)
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many requests for shared trips; try again shortly",
                            headers={"Retry-After": str(max(1, round(retry_after)))})
    try:
        parsed = uuid.UUID(public_id)
    except ValueError:
        # the same answer as for a link that doesn't exist
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    trip = sharing.find_by_public_id(db, parsed)
    if trip is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return sharing.shared_view(trip, trip_service.routes_to_show(db, trip))
