"""
Every OpenRouteService request (geocoding, directions, POIs) goes through open_json, which retries what may
succeed a moment later: a timeout, HTTP 429 and HTTP 5xx. Up to MAX_ATTEMPTS attempts, waiting with
exponential backoff and jitter between them, or as long as the Retry-After header asks. Any other 4xx (a bad
key, a bad request) fails at once, and so does an unreachable host.

Each attempt has its own timeout. All attempts together stay inside a budget: the caller's, cut short by the
agent turn's deadline when the request came from the agent (see deadline.py), so retries never run past it.
"""

from __future__ import annotations

import email.utils
import json
import random
import socket
import time
from collections.abc import Callable
from urllib import error, request

from app.services import deadline

MAX_ATTEMPTS = 3
BASE_DELAY_S = 1.0
MAX_DELAY_S = 8.0
# A Retry-After longer than this is not waited for; the call fails with the reason instead
MAX_RETRY_AFTER_S = 30.0

# Replaced in tests, so retries don't wait
sleep: Callable[[float], None] = time.sleep
jitter: Callable[[], float] = random.random


class OrsError(Exception):
    """ORS gave no usable answer. status is the last HTTP status (None for a timeout or no connection)."""

    def __init__(self, message: str, *, status: int | None = None, timed_out: bool = False, attempts: int = 1):
        super().__init__(message)
        self.status = status
        self.timed_out = timed_out
        self.attempts = attempts


def is_retryable_status(status: int) -> bool:
    return status == 429 or status >= 500


def backoff_s(attempt: int) -> float:
    """The wait after failed attempt n (1-based): 1, 2, 4... s capped at MAX_DELAY_S, each between half and all of it."""
    ceiling = min(MAX_DELAY_S, BASE_DELAY_S * 2 ** (attempt - 1))
    return ceiling / 2 + jitter() * ceiling / 2


def retry_after_s(headers) -> float | None:
    """Seconds from a Retry-After header, given as seconds or as an HTTP date; None when absent or unreadable."""
    value = headers.get("Retry-After") if headers is not None else None
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, when.timestamp() - time.time())


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    return isinstance(exc, error.URLError) and isinstance(exc.reason, (TimeoutError, socket.timeout))


def open_json(req: request.Request, *, timeout: float, budget_s: float, what: str,
              opener: Callable[..., object] | None = None) -> dict:
    """
    The JSON body of req's response, retrying as described above. Raises OrsError.

    timeout: seconds for one attempt. budget_s: seconds for all attempts and the waits between them; a retry
    that could not finish inside it (or inside the agent turn's deadline) is not started.
    what: names the request in error messages, e.g. "the fastest route".
    """
    open_ = opener or request.urlopen
    started = time.monotonic()
    remaining_turn = deadline.remaining_s()
    budget = budget_s if remaining_turn is None else min(budget_s, remaining_turn)

    attempt = 0
    while True:
        attempt += 1
        attempt_timeout = min(timeout, max(1.0, budget - (time.monotonic() - started)))
        try:
            with open_(req, timeout=attempt_timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:300] if e.fp is not None else ""
            failure = OrsError(f"OpenRouteService answered HTTP {e.code} for {what}: {body}".rstrip(": "),
                               status=e.code, attempts=attempt)
            if not is_retryable_status(e.code):
                raise failure from e
            wait = retry_after_s(e.headers)
            if wait is not None and wait > MAX_RETRY_AFTER_S:
                raise OrsError(f"{failure} (asked to retry after {wait:g} s)", status=e.code, attempts=attempt) from e
            wait = backoff_s(attempt) if wait is None else wait
            cause: BaseException = e
        except Exception as e:  # noqa: BLE001 - sorted into timeouts (retried) and everything else (not)
            if not _is_timeout(e):
                reason = e.reason if isinstance(e, error.URLError) else e
                raise OrsError(f"OpenRouteService is unreachable for {what}: {reason}", attempts=attempt) from e
            failure = OrsError(f"OpenRouteService did not answer within {attempt_timeout:g} s for {what}",
                               timed_out=True, attempts=attempt)
            wait, cause = backoff_s(attempt), e

        elapsed = time.monotonic() - started
        if attempt >= MAX_ATTEMPTS:
            raise _gave_up(failure, attempt) from cause
        if elapsed + wait + min(timeout, 1.0) > budget:
            # no time left for another attempt
            raise _gave_up(failure, attempt) from cause
        sleep(wait)


def _gave_up(failure: OrsError, attempts: int) -> OrsError:
    note = f" (after {attempts} attempts)" if attempts > 1 else ""
    return OrsError(f"{failure}{note}", status=failure.status, timed_out=failure.timed_out, attempts=attempts)
