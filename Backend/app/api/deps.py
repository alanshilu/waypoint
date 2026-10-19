"""Access rules for a public deployment (PUBLIC_DEMO). With it off, both dependencies let everything through."""

import secrets

from fastapi import Header, HTTPException

from app.core.config import settings
from app.core.internal import INTERNAL_HEADER


def internal_only(x_waypoint_internal: str | None = Header(default=None, alias=INTERNAL_HEADER)) -> None:
    """In a public demo, only the agent (which sends the shared secret) may call this endpoint."""
    if not settings.public_demo:
        return
    secret = settings.internal_api_secret or ""
    if not x_waypoint_internal or not secrets.compare_digest(x_waypoint_internal.encode(), secret.encode()):
        raise HTTPException(status_code=403, detail="This endpoint is not available in the public demo")


def not_in_public_demo() -> None:
    """In a public demo, this endpoint does not exist."""
    if settings.public_demo:
        raise HTTPException(status_code=404, detail="Not Found")
