"""
Retries of OpenRouteService calls (ors_http.open_json), the agent turn's deadline that bounds them, and tool
calls that fail being reported as failed. The HTTP layer is mocked: no network is used.
"""

import io
import json
import socket
import time
from email.utils import formatdate
from types import SimpleNamespace
from urllib import error

import pytest
from anthropic.types.beta import BetaMessage, BetaTextBlock, BetaToolUseBlock, BetaUsage
from fastapi.testclient import TestClient

from app.agent.orchestrator import Agent
from app.agent.tools import find_places as find_places_tool
from app.agent.tools import generate_route as generate_route_tool
from app.agent.tools import geocode_location as geocode_tool
from app.api.v1.endpoints import location as location_api
from app.core.config import settings
from app.main import app
from app.services import deadline, geocoding_service, ors_http, poi_service, routing_service
from app.services.ors_http import OrsError


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    """Records each wait instead of sleeping; jitter fixed at its maximum, so backoff is 1, 2, 4... s."""
    waits: list[float] = []
    monkeypatch.setattr(ors_http, "sleep", waits.append)
    monkeypatch.setattr(ors_http, "jitter", lambda: 1.0)
    return waits


def http_error(status: int, headers: dict | None = None, body: str = "") -> error.HTTPError:
    return error.HTTPError("https://api.openrouteservice.org/x", status, "error", headers or {}, io.BytesIO(body.encode()))


class Response:
    def __init__(self, data):
        self._body = json.dumps(data).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Opener:
    """Answers with the queued outcomes in order (an exception is raised); records each attempt's timeout."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.timeouts: list[float] = []

    def __call__(self, req, timeout):
        self.timeouts.append(timeout)
        item = self.outcomes.pop(0)
        if isinstance(item, BaseException):
            raise item
        return Response(item)


def call(opener, timeout=10, budget_s=60):
    return ors_http.open_json(SimpleNamespace(), timeout=timeout, budget_s=budget_s, what="the test", opener=opener)


# --- open_json ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("first", [
    http_error(500), http_error(502), http_error(503), http_error(504), http_error(429),
    TimeoutError("read timed out"), socket.timeout("timed out"), error.URLError(TimeoutError("timed out")),
])
def test_succeeds_on_retry(no_waiting, first):
    opener = Opener(first, {"ok": True})
    assert call(opener) == {"ok": True}
    assert len(opener.timeouts) == 2
    assert no_waiting == [1.0]  # the first backoff


def test_backoff_grows_and_has_jitter(monkeypatch, no_waiting):
    opener = Opener(http_error(503), http_error(503), {"ok": True})
    assert call(opener) == {"ok": True}
    assert no_waiting == [1.0, 2.0]
    monkeypatch.setattr(ors_http, "jitter", lambda: 0.0)
    assert [ors_http.backoff_s(n) for n in (1, 2, 3, 5)] == [0.5, 1.0, 2.0, 4.0]  # half the ceiling, at least


def test_honours_retry_after_seconds(no_waiting):
    opener = Opener(http_error(429, {"Retry-After": "7"}), {"ok": True})
    assert call(opener) == {"ok": True}
    assert no_waiting == [7.0]


def test_honours_retry_after_as_a_date(no_waiting):
    when = formatdate(time.time() + 5, usegmt=True)
    opener = Opener(http_error(503, {"Retry-After": when}), {"ok": True})
    assert call(opener) == {"ok": True}
    assert 3.0 <= no_waiting[0] <= 5.0


def test_a_retry_after_too_long_to_wait_for_fails_at_once(no_waiting):
    opener = Opener(http_error(429, {"Retry-After": "120"}), {"ok": True})
    with pytest.raises(OrsError, match="asked to retry after 120 s") as caught:
        call(opener)
    assert caught.value.status == 429 and no_waiting == []


def test_gives_up_cleanly_after_three_attempts(no_waiting):
    opener = Opener(http_error(502, body="upstream down"), http_error(502), http_error(503, body="still down"))
    with pytest.raises(OrsError) as caught:
        call(opener)
    assert caught.value.attempts == 3
    assert caught.value.status == 503 and not caught.value.timed_out
    assert str(caught.value) == "OpenRouteService answered HTTP 503 for the test: still down (after 3 attempts)"
    assert len(opener.timeouts) == 3 and no_waiting == [1.0, 2.0]


def test_gives_up_on_timeouts_as_a_timeout():
    opener = Opener(TimeoutError(), TimeoutError(), TimeoutError())
    with pytest.raises(OrsError) as caught:
        call(opener)
    assert caught.value.timed_out and caught.value.attempts == 3


@pytest.mark.parametrize("status", [400, 401, 403, 404, 413])
def test_no_retry_on_other_4xx(no_waiting, status):
    opener = Opener(http_error(status, body="bad key"), {"ok": True})
    with pytest.raises(OrsError) as caught:
        call(opener)
    assert caught.value.status == status and caught.value.attempts == 1
    assert len(opener.timeouts) == 1 and no_waiting == []


def test_no_retry_when_unreachable(no_waiting):
    opener = Opener(error.URLError(ConnectionRefusedError("refused")), {"ok": True})
    with pytest.raises(OrsError, match="unreachable"):
        call(opener)
    assert len(opener.timeouts) == 1 and no_waiting == []


def test_each_attempt_gets_its_own_timeout():
    opener = Opener(TimeoutError(), TimeoutError(), {"ok": True})
    call(opener, timeout=12, budget_s=100)
    assert opener.timeouts == [12, 12, 12]


def test_no_retry_that_would_not_fit_in_the_budget(no_waiting):
    # the 1 s backoff plus at least 1 s for another attempt does not fit in 1.5 s
    opener = Opener(http_error(503), {"ok": True})
    with pytest.raises(OrsError):
        call(opener, budget_s=1.5)
    assert len(opener.timeouts) == 1 and no_waiting == []


def test_the_turn_deadline_cuts_the_budget(no_waiting):
    opener = Opener(http_error(503), {"ok": True})
    with deadline.until(time.time() + 1.5), pytest.raises(OrsError):
        call(opener, budget_s=300)
    assert len(opener.timeouts) == 1


def test_an_attempt_never_waits_past_the_turn_deadline():
    opener = Opener({"ok": True})
    with deadline.until(time.time() + 20):
        call(opener, timeout=90, budget_s=300)
    assert 18 < opener.timeouts[0] <= 20


# --- the ORS callers ---------------------------------------------------------------------------------------

ORS_ROUTE = {"features": [{"geometry": {"coordinates": [[-122.4, 37.8, 10], [-118.2, 34.1, 20]]},
                           "properties": {"segments": [{"distance": 16093.4, "duration": 600, "ascent": 5,
                                                        "descent": 3, "steps": []}]}}]}


def test_directions_retry_with_the_route_timeout_per_attempt(monkeypatch):
    opener = Opener(http_error(429), ORS_ROUTE)
    monkeypatch.setattr(routing_service.request, "urlopen", opener)
    route = routing_service.get_single_route(-122.4, 37.8, -118.2, 34.1)
    assert route["distance_miles"] == 10.0
    assert opener.timeouts == [settings.ors_route_timeout_s] * 2


def test_directions_give_up_as_a_routing_error(monkeypatch):
    monkeypatch.setattr(routing_service.request, "urlopen", Opener(TimeoutError(), TimeoutError(), TimeoutError()))
    with pytest.raises(routing_service.RoutingError) as caught:
        routing_service.get_single_route(0, 0, 1, 1)
    assert caught.value.timed_out and "after 3 attempts" in str(caught.value)


def test_both_routes_see_the_turn_deadline(monkeypatch):
    seen = []

    def record(*args, preference="fastest", avoid_features=None):
        seen.append(deadline.remaining_s())
        return {}

    monkeypatch.setattr(routing_service, "get_single_route", record)
    with deadline.until(time.time() + 100):
        routing_service.get_route_options(0, 0, 1, 1)
    assert len(seen) == 2 and all(s is not None and 90 < s <= 100 for s in seen)


def test_geocoding_retries_then_fails_without_the_key_in_the_message(monkeypatch):
    monkeypatch.setattr(geocoding_service.request, "urlopen", Opener(http_error(503), http_error(503), http_error(503)))
    with pytest.raises(OrsError) as caught:
        geocoding_service.search_address("Fresno, CA")
    assert caught.value.attempts == 3
    assert settings.ors_api_key not in str(caught.value) and "api_key" not in str(caught.value)


def test_geocoding_does_not_retry_a_rejected_key(monkeypatch):
    opener = Opener(http_error(403, body="Access to this API has been disallowed"))
    monkeypatch.setattr(geocoding_service.request, "urlopen", opener)
    with pytest.raises(OrsError) as caught:
        geocoding_service.search_address("Fresno, CA")
    assert caught.value.status == 403 and len(opener.timeouts) == 1


def test_poi_search_retries(monkeypatch):
    monkeypatch.setattr(poi_service.request, "urlopen", Opener(http_error(500), {"features": []}))
    assert poi_service.fetch_pois_from_ors(0, 0, 1, 1) == []


def test_geocode_endpoint_reports_the_upstream_failure(monkeypatch):
    def failing(q):
        raise OrsError("OpenRouteService did not answer within 10 s (after 3 attempts)", timed_out=True, attempts=3)

    monkeypatch.setattr(location_api, "search_address", failing)
    r = TestClient(app).get("/location/search", params={"q": "Fresno"})
    assert r.status_code == 504
    assert r.json()["detail"].endswith("(after 3 attempts)")


def test_the_deadline_header_reaches_the_endpoint(monkeypatch):
    seen = []

    def record(q):
        seen.append(deadline.remaining_s())
        return []

    monkeypatch.setattr(location_api, "search_address", record)
    client = TestClient(app)
    client.get("/location/search", params={"q": "Fresno"}, headers={"X-Waypoint-Deadline": f"{time.time() + 60}"})
    client.get("/location/search", params={"q": "Fresno"})
    assert 55 < seen[0] <= 60 and seen[1] is None


def test_route_retries_must_fit_inside_the_agent_timeout():
    from app.core.config import Settings

    with pytest.raises(ValueError, match="less than AGENT_TIMEOUT_S"):
        Settings(_env_file=None, DATABASE_URL="postgresql://u:p@h/d", ORS_API_KEY="k",
                 AGENT_TIMEOUT_S=200, ORS_ROUTE_RETRY_BUDGET_S=300)


# --- failed tool calls show as failed ----------------------------------------------------------------------

def usage():
    return BetaUsage.model_construct(input_tokens=10, output_tokens=5, cache_read_input_tokens=0,
                                     cache_creation_input_tokens=0)


def turn_with(tool: str, args: dict):
    """The model calls one tool, then answers."""
    final = {"summary": "The route service is down.", "recommended_route_type": "none",
             "departure_window": {"start": "", "end": "", "reason": ""}, "stops": [], "places": [],
             "warnings": ["Routes could not be generated."]}
    return [
        BetaMessage.model_construct(id="m1", type="message", role="assistant", model="t", stop_details=None,
                                    content=[BetaToolUseBlock.model_construct(type="tool_use", id="tu_1", name=tool,
                                                                              input=args)],
                                    stop_reason="tool_use", usage=usage()),
        BetaMessage.model_construct(id="m2", type="message", role="assistant", model="t", stop_details=None,
                                    content=[BetaTextBlock.model_construct(type="text", text=json.dumps(final))],
                                    stop_reason="end_turn", usage=usage()),
    ]


class Clients:
    def __init__(self, responses):
        self.responses = responses
        self.sent = []

    def open(self, api_key):
        clients = self

        class Messages:
            def create(self, **kwargs):
                clients.sent.append(list(kwargs["messages"]))  # as sent; the agent appends to it afterwards
                return clients.responses.pop(0)

        from contextlib import nullcontext
        return nullcontext(SimpleNamespace(beta=SimpleNamespace(messages=Messages())))


def run_one(tool_name, tool, args):
    clients = Clients(turn_with(tool_name, args))
    events = []
    turn = Agent(clients, {tool_name: tool}, []).run([], "SF to LA", events.append)
    return turn, events, clients.sent[-1][-1]["content"][0]


def test_a_handled_ors_failure_is_a_failed_step(monkeypatch):
    response = SimpleNamespace(status_code=504, text="", json=lambda: {"detail": "OpenRouteService did not answer "
                                                                               "within 90 s (after 3 attempts)"})
    monkeypatch.setattr(generate_route_tool.requests, "post", lambda *a, **k: response)
    turn, events, tool_result = run_one("generate_routes", generate_route_tool.generate_routes, {"trip_id": 1})

    step = turn.steps[0]
    assert step.error == "OpenRouteService did not answer within 90 s (after 3 attempts)"
    assert step.result is None
    assert [e["error"] for e in events if e["type"] == "tool_end"] == [step.error]
    # the model is told it failed too
    assert tool_result["is_error"] is True
    assert tool_result["content"] == f"Error calling generate_routes: {step.error}"


def test_a_place_that_is_not_found_is_a_failed_step(monkeypatch):
    response = SimpleNamespace(status_code=200, text="", json=lambda: {"results": []})
    monkeypatch.setattr(geocode_tool.requests, "get", lambda *a, **k: response)
    turn, events, _ = run_one("geocode_location", geocode_tool.geocode_location, {"query": "Nowhere"})
    assert turn.steps[0].error == "No location found for 'Nowhere'"


def test_a_geocoder_outage_is_a_failed_step(monkeypatch):
    response = SimpleNamespace(status_code=502, text="", json=lambda: {"detail": "OpenRouteService answered HTTP 503"})
    monkeypatch.setattr(geocode_tool.requests, "get", lambda *a, **k: response)
    turn, _, _ = run_one("geocode_location", geocode_tool.geocode_location, {"query": "Fresno"})
    assert turn.steps[0].error == "OpenRouteService answered HTTP 503"


def test_a_place_search_that_failed_everywhere_is_a_failed_step(monkeypatch):
    note = "Search for places to stay unavailable: Overpass timed out; fallback failed: HTTP 503"
    body = {"groups": [{"near": "n1", "kind": "stay", "source": "none", "places": [], "note": note},
                       {"near": "n1", "kind": "food", "source": "none", "places": [], "note": "Food search unavailable"}]}
    response = SimpleNamespace(status_code=200, text="", json=lambda: body)
    monkeypatch.setattr(find_places_tool.requests, "post", lambda *a, **k: response)
    points = [{"near": "n1", "lat": 35.0, "lon": -119.0, "kinds": ["stay", "food"]}]
    turn, _, _ = run_one("find_places", find_places_tool.find_places, {"points": points})
    assert turn.steps[0].error == f"Place search failed: {note}"


def test_a_place_search_that_found_some_groups_is_not_failed(monkeypatch):
    body = {"groups": [{"near": "n1", "kind": "stay", "source": "overpass", "places": [{"id": "a"}]},
                       {"near": "n1", "kind": "food", "source": "none", "places": [], "note": "Food search unavailable"}]}
    response = SimpleNamespace(status_code=200, text="", json=lambda: body)
    monkeypatch.setattr(find_places_tool.requests, "post", lambda *a, **k: response)
    points = [{"near": "n1", "lat": 35.0, "lon": -119.0, "kinds": ["stay", "food"]}]
    turn, _, _ = run_one("find_places", find_places_tool.find_places, {"points": points})
    assert turn.steps[0].error is None


def test_tools_send_the_turn_deadline_and_never_wait_past_it(monkeypatch):
    sent = {}

    def post(url, params=None, headers=None, timeout=None):
        sent.update(headers=headers, timeout=timeout)
        return SimpleNamespace(status_code=200, json=lambda: {"routes": []})

    monkeypatch.setattr(generate_route_tool.requests, "post", post)
    with deadline.until(time.time() + 40):
        generate_route_tool.generate_routes(1)
    assert float(sent["headers"]["X-Waypoint-Deadline"]) > time.time()
    assert 35 < sent["timeout"] <= 40


def test_a_tool_called_after_the_deadline_fails_without_calling_the_api(monkeypatch):
    monkeypatch.setattr(generate_route_tool.requests, "post", lambda *a, **k: pytest.fail("called the API"))
    with deadline.until(time.time() - 1), pytest.raises(Exception, match="ran out of time"):
        generate_route_tool.generate_routes(1)
