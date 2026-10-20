"""The shared-secret header the agent's tools send when they call this API over HTTP."""

from app.core.config import settings

INTERNAL_HEADER = "X-Waypoint-Internal"


def internal_headers() -> dict[str, str]:
    """Headers for an internal call; empty when no secret is configured (local development)."""
    return {INTERNAL_HEADER: settings.internal_api_token} if settings.internal_api_token else {}
