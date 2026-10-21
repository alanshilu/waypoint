"""
The agent endpoints' errors, always {"error": {"code", "message"}} with a matching status, and the user's own
Anthropic key (bring your own key), checked before anything runs.
"""

from __future__ import annotations

import re

import anthropic
from fastapi.responses import JSONResponse

from app.core.config import settings

OWN_KEY_HEADER = "X-Anthropic-Key"
OWN_KEY_PATTERN = re.compile(r"sk-ant-[A-Za-z0-9_-]{20,250}")


class AgentError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.headers = status, code, message, headers or {}

    def body(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}

    def response(self) -> JSONResponse:
        return JSONResponse(status_code=self.status, content=self.body(), headers=self.headers)


def retry_after(seconds: float) -> dict:
    return {"Retry-After": str(max(1, round(seconds)))}


def own_key(header: str | None) -> str | None:
    """
    The user's own Anthropic key from the X-Anthropic-Key header, or None to use the server's key.

    Bring your own key: the key is used for this one turn and then dropped. It is never stored in the
    session, written to the database, logged or returned, and no error message repeats it.
    """
    if not header or not header.strip():
        return None
    key = header.strip()
    if not OWN_KEY_PATTERN.fullmatch(key):
        raise AgentError(400, "invalid_api_key", "That doesn't look like an Anthropic API key (it starts with sk-ant-)")
    return key


def classify(exc: BaseException, own: bool = False) -> AgentError:
    """Maps a failure while running the agent to a clean error. own: the turn ran on the user's key."""
    if isinstance(exc, AgentError):
        return exc
    if own:
        # the user's key is the likely cause; say so, without repeating the key
        if isinstance(exc, anthropic.AuthenticationError):
            return AgentError(401, "invalid_api_key", "Anthropic rejected your API key; check it and try again")
        if isinstance(exc, (anthropic.PermissionDeniedError, anthropic.NotFoundError)):
            return AgentError(403, "api_key_forbidden", f"Your Anthropic key can't use the model {settings.agent_model}")
        if isinstance(exc, anthropic.RateLimitError):
            return AgentError(429, "api_key_rate_limited", "Your Anthropic key is being rate limited; try again shortly")
        if isinstance(exc, anthropic.BadRequestError) and "credit balance" in str(exc).lower():
            return AgentError(402, "api_key_no_credit", "Your Anthropic account is out of credit")
    if isinstance(exc, TimeoutError):
        return AgentError(504, "agent_timeout", f"The agent did not finish within {settings.agent_timeout_s:g} s")
    if isinstance(exc, anthropic.RateLimitError):
        return AgentError(503, "model_rate_limited", "The model API is rate limiting requests; try again shortly")
    if isinstance(exc, anthropic.APIStatusError):
        return AgentError(502, "model_api_error", f"The model API returned {exc.status_code}")
    if isinstance(exc, anthropic.APIConnectionError):
        return AgentError(502, "model_api_unreachable", "Could not reach the model API")
    return AgentError(500, "agent_error", f"The agent failed: {type(exc).__name__}")
