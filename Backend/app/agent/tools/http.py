"""
How the agent's tools call this API: with the turn's deadline passed on, a timeout that never runs past it, and
a failed call reported with the API's own reason, not just the status.
"""

from app.core.internal import internal_headers
from app.services import deadline


class ToolCallError(Exception):
    """The API answered with an error. The message names the endpoint, the status and the API's detail."""


def headers(internal: bool = False) -> dict[str, str]:
    """The turn's deadline header, plus the internal-call secret for endpoints that need it."""
    return {**deadline.headers(), **(internal_headers() if internal else {})}


def timeout(seconds: float | None) -> float | None:
    """
    How long a tool waits for this API: `seconds` (None for no limit), cut to what is left of the agent turn.
    Raises ToolCallError when the turn has no time left.
    """
    left = deadline.remaining_s()
    if left is None:
        return seconds
    if left <= 0:
        raise ToolCallError("The agent turn ran out of time before this call")
    return left if seconds is None else min(seconds, left)


def check(response) -> None:
    """Raises ToolCallError for a 4xx/5xx response; the agent and the app's trace show its message."""
    if response.status_code < 400:
        return
    try:
        body = response.json()
        detail = body.get("detail") or body.get("error", {}).get("message") or response.text
    except ValueError:
        detail = response.text
    path = getattr(getattr(response, "request", None), "path_url", "") or getattr(response, "url", "")
    raise ToolCallError(f"{path.split('?')[0]} answered HTTP {response.status_code}: {str(detail)[:300]}")
