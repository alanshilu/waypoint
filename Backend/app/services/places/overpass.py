"""
OpenStreetMap through the Overpass API: one query for every search, sent to public servers in a hedged
sequence. Overpass is a free service with a fair-use policy: a second server is only asked when the first
fails or is slow, and a User-Agent names the app.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from urllib import error, parse, request

from app.services.places.osm import CAMPING_RADIUS_KM, CAMPING_TAGS, FOOD_RADIUS_KM, FOOD_TAGS, Search
from app.services.places.sources import PlacesError

# Public Overpass servers swing between answering in seconds and taking minutes. A search waits for them:
# we set no deadline of our own, the app shows the user it's still searching, and the next server also
# starts when one fails or hasn't answered within HEDGE_AFTER_S, so the first answer wins.
# The one bound is Overpass's: a query runs at most QUERY_TIMEOUT_S on the server (180 s, its standard
# maximum) and then fails there. The read timeout only notices a connection that went silent past that.
QUERY_TIMEOUT_S = 180
READ_TIMEOUT_S = QUERY_TIMEOUT_S + 30
HEDGE_AFTER_S = 6
USER_AGENT = "Waypoint road-trip planner (https://github.com/alanshilu/waypoint)"

# (url, query, timeout_s) -> elements; raises PlacesError
RequestOnce = Callable[[str, str, float], list[dict]]


def _bbox(lat: float, lon: float, radius_km: float) -> str:
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(0.1, math.cos(math.radians(lat))))
    return f"{lat - dlat:.4f},{lon - dlon:.4f},{lat + dlat:.4f},{lon + dlon:.4f}"


def build_query(searches: list[Search], food_radius_km: float = FOOD_RADIUS_KM, timeout_s: float = QUERY_TIMEOUT_S) -> str:
    """One Overpass QL query for every (kind, lat, lon) search; boxes, trimmed to the radius afterwards."""
    parts = []
    for kind, lat, lon in searches:
        if kind == "camping":
            parts.append(f'nwr["tourism"~"^({"|".join(CAMPING_TAGS)})$"]({_bbox(lat, lon, CAMPING_RADIUS_KM)});')
        else:
            parts.append(f'nwr["amenity"~"^({"|".join(FOOD_TAGS)})$"]({_bbox(lat, lon, food_radius_km)});')
    return f"[out:json][timeout:{int(timeout_s)}];({''.join(parts)});out center tags;"


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
        raise PlacesError(f"OpenStreetMap (Overpass) went silent for {timeout:.0f} s", timed_out=True) from e
    except error.URLError as e:
        if isinstance(e.reason, TimeoutError):
            raise PlacesError(f"OpenStreetMap (Overpass) went silent for {timeout:.0f} s", timed_out=True) from e
        raise PlacesError(f"OpenStreetMap (Overpass) is unreachable: {e.reason}") from e


class OverpassSource:
    """A PlaceSource over the given Overpass servers, asked in a hedged sequence, waited for without a deadline."""

    name = "openstreetmap"

    def __init__(self, urls: list[str], request_once: RequestOnce = request_once,
                 query_timeout_s: float = QUERY_TIMEOUT_S, read_timeout_s: float = READ_TIMEOUT_S,
                 hedge_after_s: float = HEDGE_AFTER_S):
        self.urls = list(urls)
        self._request_once = request_once
        self.query_timeout_s = query_timeout_s
        self.read_timeout_s = read_timeout_s
        self.hedge_after_s = hedge_after_s

    def search(self, searches: list[Search], food_radius_km: float) -> list[dict]:
        return self.query(build_query(searches, food_radius_km, self.query_timeout_s))

    def query(self, query: str) -> list[dict]:
        """
        The first answer to this query from the servers. Raises PlacesError when every server failed.

        Hedged: the first server is asked, and the next one too as soon as a request fails or hedge_after_s
        passes without an answer; whichever answers first wins, however long it takes. A healthy first
        server is the only one asked.
        """
        urls = list(self.urls)
        if not urls:
            raise PlacesError("No OpenStreetMap (Overpass) server is configured")
        errors: list[PlacesError] = []
        pool = ThreadPoolExecutor(max_workers=len(urls), thread_name_prefix="overpass")
        pending = {pool.submit(self._request_once, urls.pop(0), query, self.read_timeout_s)}
        try:
            while pending:
                done, pending = wait(pending, timeout=self.hedge_after_s if urls else None, return_when=FIRST_COMPLETED)
                for future in done:
                    try:
                        return future.result()
                    except PlacesError as e:
                        errors.append(e)
                # a server failed, or is taking a while: ask the next one too
                if urls:
                    pending.add(pool.submit(self._request_once, urls.pop(0), query, self.read_timeout_s))
        finally:
            # a slower server's request still running ends on its own; nothing waits for it
            pool.shutdown(wait=False, cancel_futures=True)
        # a timeout says more about why the search failed than a quick 502 from another server
        raise next((e for e in errors if e.timed_out), errors[-1])
