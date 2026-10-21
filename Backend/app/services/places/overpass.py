"""
OpenStreetMap through the Overpass API: one query for every search, sent to public servers in a hedged
sequence. Overpass is a free service with a fair-use policy: a second server is only asked when the first
fails or is slow, and a User-Agent names the app.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from urllib import error, parse, request

from app.services.places.osm import CAMPING_RADIUS_KM, CAMPING_TAGS, FOOD_RADIUS_KM, FOOD_TAGS, Search
from app.services.places.sources import PlacesError

# Public Overpass servers swing between answering in seconds and not at all: on 2026-10-21 one returned
# 502 at once and the others timed out at 90 s on the smallest query, then minutes later the same search
# took 19 s. So no single request waits long, and the next server starts when one fails or hasn't
# answered within HEDGE_AFTER_S; the first answer wins.
TIMEOUT_S = 30
HEDGE_AFTER_S = 6
USER_AGENT = "Waypoint road-trip planner (https://github.com/alanshilu/waypoint)"

# (url, query, timeout_s) -> elements; raises PlacesError
RequestOnce = Callable[[str, str, float], list[dict]]


def _bbox(lat: float, lon: float, radius_km: float) -> str:
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(0.1, math.cos(math.radians(lat))))
    return f"{lat - dlat:.4f},{lon - dlon:.4f},{lat + dlat:.4f},{lon + dlon:.4f}"


def build_query(searches: list[Search], food_radius_km: float = FOOD_RADIUS_KM, timeout_s: float = TIMEOUT_S) -> str:
    """One Overpass QL query for every (kind, lat, lon) search; boxes, trimmed to the radius afterwards."""
    parts = []
    for kind, lat, lon in searches:
        if kind == "camping":
            parts.append(f'nwr["tourism"~"^({"|".join(CAMPING_TAGS)})$"]({_bbox(lat, lon, CAMPING_RADIUS_KM)});')
        else:
            parts.append(f'nwr["amenity"~"^({"|".join(FOOD_TAGS)})$"]({_bbox(lat, lon, food_radius_km)});')
    return f"[out:json][timeout:{int(timeout_s) - 5}];({''.join(parts)});out center tags;"


def request_once(url: str, query: str, timeout: float, user_agent: str = USER_AGENT) -> list[dict]:
    """One POST to one Overpass server. Raises PlacesError."""
    data = parse.urlencode({"data": query}).encode()
    req = request.Request(url, data=data, headers={"User-Agent": user_agent}, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")).get("elements", [])
    except error.HTTPError as e:
        busy = e.code in (429, 502, 503, 504)
        raise PlacesError(f"OpenStreetMap (Overpass) is {'busy' if busy else 'failing'}: HTTP {e.code}",
                          timed_out=e.code == 504) from e
    except TimeoutError as e:
        raise PlacesError(f"OpenStreetMap (Overpass) did not answer within {timeout:.0f} s", timed_out=True) from e
    except error.URLError as e:
        if isinstance(e.reason, TimeoutError):
            raise PlacesError(f"OpenStreetMap (Overpass) did not answer within {timeout:.0f} s", timed_out=True) from e
        raise PlacesError(f"OpenStreetMap (Overpass) is unreachable: {e.reason}") from e


class OverpassSource:
    """A PlaceSource over the given Overpass servers, asked in a hedged sequence."""

    name = "openstreetmap"

    def __init__(self, urls: list[str], request_once: RequestOnce = request_once,
                 timeout_s: float = TIMEOUT_S, hedge_after_s: float = HEDGE_AFTER_S):
        self.urls = list(urls)
        self._request_once = request_once
        self.timeout_s = timeout_s
        self.hedge_after_s = hedge_after_s

    def search(self, searches: list[Search], food_radius_km: float, budget_s: float) -> list[dict]:
        return self.query(build_query(searches, food_radius_km, self.timeout_s), budget_s)

    def query(self, query: str, budget_s: float) -> list[dict]:
        """
        The first answer to this query from the servers, within budget_s. Raises PlacesError.

        Hedged: the first server is asked, and the next one too as soon as a request fails or hedge_after_s
        passes without an answer; whichever answers first wins. A failing or stalled server costs seconds
        instead of the whole budget, and a healthy first server is the only one asked.
        """
        urls = list(self.urls)
        if not urls:
            raise PlacesError("No OpenStreetMap (Overpass) server is configured")
        deadline = time.monotonic() + budget_s
        errors: list[PlacesError] = []
        pending: set = set()
        pool = ThreadPoolExecutor(max_workers=len(urls), thread_name_prefix="overpass")
        try:
            while True:
                left = deadline - time.monotonic()
                if urls and left >= 5:
                    pending.add(pool.submit(self._request_once, urls.pop(0), query, min(self.timeout_s, left)))
                if not pending or left <= 0:
                    break
                done, pending = wait(pending, timeout=min(self.hedge_after_s, left) if urls else left,
                                     return_when=FIRST_COMPLETED)
                for future in done:
                    try:
                        return future.result()
                    except PlacesError as e:
                        errors.append(e)
        finally:
            # a request still running ends on its own timeout; nothing waits for it
            pool.shutdown(wait=False, cancel_futures=True)
        if pending or not errors:
            errors.append(PlacesError(f"OpenStreetMap (Overpass) did not answer within {budget_s:.0f} s",
                                      timed_out=True))
        # a timeout says more about why the search was slow than a quick 502 from another server
        raise next((e for e in errors if e.timed_out), errors[-1])
