"""How the agent's tools report a failed call to this API: with the API's own reason, not just the status."""


class ToolCallError(Exception):
    """The API answered with an error. The message names the endpoint, the status and the API's detail."""


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
