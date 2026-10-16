"""
Checks for agent sessions. Each check takes a Session and returns a
CheckResult(passed, evidence). Evidence lists the offending text or tool call,
so a failure can be read without re-running the case.

All checks are deterministic except concise_reply, which also asks an LLM
judge (one call per turn).
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Session model (filled in by run.py)
# ---------------------------------------------------------------------------


@dataclass
class TurnRecord:
    prompt: str
    reply: str
    final_answer: dict | None
    steps: list  # app.agent.orchestrator.Step, with full_result


@dataclass
class Session:
    case_id: str
    turns: list[TurnRecord]


@dataclass
class CheckResult:
    passed: bool
    evidence: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"passed": self.passed, "evidence": self.evidence, "notes": self.notes}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Points within this distance count as "the same place"
NEAR_KM = 25.0
# Keys whose numbers are coordinates, never quantities a reply should quote
COORDINATE_KEYS = {"geometry", "coordinates", "lat", "lon", "center"}


def executed(steps):
    """Steps that actually ran and succeeded (not served from the per-turn cache)."""
    return [s for s in steps if s.error is None and not getattr(s, "cached", False)]


def results(steps, tool):
    """(args, full_result) for each successful call of `tool`."""
    return [(s.args, s.full_result) for s in steps if s.tool == tool and s.error is None]


def session_steps(session: Session, upto: int | None = None):
    turns = session.turns if upto is None else session.turns[: upto + 1]
    return [s for t in turns for s in t.steps]


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(min(1.0, h)))


def point_segment_km(lat, lon, a, b) -> float:
    """Distance from (lat, lon) to the segment a-b ([lon, lat] pairs), equirectangular approximation."""
    kx = 111.32 * math.cos(math.radians(lat))
    ky = 110.57
    px, py = 0.0, 0.0
    ax, ay = (a[0] - lon) * kx, (a[1] - lat) * ky
    bx, by = (b[0] - lon) * kx, (b[1] - lat) * ky
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    t = 0.0 if length_sq == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    return math.hypot(ax + t * dx - px, ay + t * dy - py)


def distance_to_line_km(lat, lon, coords) -> float:
    if not coords:
        return math.inf
    if len(coords) == 1:
        return haversine_km(lat, lon, coords[0][1], coords[0][0])
    return min(point_segment_km(lat, lon, a, b) for a, b in zip(coords, coords[1:], strict=False))


def walk(value, path=()):
    """Yields (key_path, leaf) for every leaf in a JSON-like value."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield from walk(v, (*path, str(k)))
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from walk(v, path)
    else:
        yield path, value


def plan_stops_of(steps) -> list[dict]:
    stops = []
    for _, result in results(steps, "plan_stops"):
        if isinstance(result, dict):
            stops.extend(result.get("stops") or [])
    return stops


def plan_starts_of(steps) -> list[str]:
    return [r.get("start") for _, r in results(steps, "plan_stops") if isinstance(r, dict) and r.get("start")]


def routes_of(steps) -> list[dict]:
    routes = []
    for _, result in results(steps, "generate_routes"):
        if isinstance(result, dict):
            routes.extend(result.get("routes") or [])
    return routes


def route_coords(route: dict) -> list:
    geometry = route.get("geometry")
    if isinstance(geometry, dict):
        return geometry.get("coordinates") or []
    if isinstance(geometry, str) and geometry.upper().startswith("LINESTRING"):
        inner = geometry[geometry.index("(") + 1 : geometry.rindex(")")]
        return [[float(x) for x in pair.split()] for pair in inner.split(",")]
    return []


def trip_endpoints(steps):
    """(origin, destination) as (lat, lon) from the last create_trip call, or (None, None)."""
    calls = [s for s in steps if s.tool == "create_trip" and s.error is None]
    if not calls:
        return None, None
    a = calls[-1].args
    try:
        return (a["origin_lat"], a["origin_lon"]), (a["destination_lat"], a["destination_lon"])
    except KeyError:
        return None, None


def reply_text(turn: TurnRecord) -> str:
    return turn.reply or ""


# ---------------------------------------------------------------------------
# a. numeric_grounding
# ---------------------------------------------------------------------------

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:T[\d:.+-]+Z?)?\b")
NAMED_DATE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b",
    re.I)
DAY_MONTH_DATE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b", re.I)
SLASH_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
CLOCK_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)|\b(\d{1,2}):(\d{2})\b", re.I)
DURATION = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hours?)\b(?:\s*(?:and\s*)?(\d+)\s*(?:m|min|mins|minutes?)\b)?"
    r"|\b(\d+)\s*(?:min|mins|minutes)\b",
    re.I)
ROAD_NAME = re.compile(r"\b(?:I|US|SR|CA|TX|NM|AZ|Hwy|Highway|Route|Interstate|State Route)[- ]?\d+[A-Z]?\b", re.I)
# A number not glued to letters on its left; units may follow ("2.4x", "383mi")
NUMBER = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?![\d])")

# A number written as an id: "#27", "route 27", "trip id 14"
ID_CONTEXT = re.compile(r"(#|\b(?:trip|route|stop|id)\s*(?:id\s*)?#?\s*)$", re.I)

# Fields whose values the reply may legitimately convert or compare
KEY_FIELDS = {
    "distance_miles", "duration_seconds", "ascent_m", "descent_m", "scenic_score", "duration_vs_fastest",
    "cumulative_miles", "cumulative_drive_hours", "temp_max", "temp_min", "precip_probability", "count",
}

# Documented derivations. Each maps one grounded value, or a pair of values of
# the same field, to a number a reply may show. Anything not produced by these
# (or present verbatim) is flagged.
UNARY_DERIVATIONS: dict[str, Callable[[str, float], float | None]] = {
    "seconds to hours": lambda k, v: v / 3600 if k == "duration_seconds" else None,
    "seconds to minutes": lambda k, v: v / 60 if k == "duration_seconds" else None,
    "metres to feet": lambda k, v: v * 3.28084 if k in ("ascent_m", "descent_m") else None,
    "miles to km": lambda k, v: v * 1.60934 if k in ("distance_miles", "cumulative_miles") else None,
    "ratio to percent": lambda k, v: v * 100 if k == "duration_vs_fastest" else None,
    "ratio to percent longer": lambda k, v: (v - 1) * 100 if k == "duration_vs_fastest" else None,
}
PAIR_DERIVATIONS: dict[str, Callable[[float, float], float | None]] = {
    "difference": lambda a, b: a - b,
    "ratio": lambda a, b: a / b if b else None,
    "percent more": lambda a, b: (a / b - 1) * 100 if b else None,
    "difference in hours": lambda a, b: (a - b) / 3600,
    "difference in minutes": lambda a, b: (a - b) / 60,
}


def _grounded_values(steps, prompts) -> tuple[list[float], list[float], list[tuple[str, float]], list[float]]:
    """Plain numbers, durations in seconds, (key, value) pairs for derivations, and database ids."""
    plain: list[float] = []
    ids: list[float] = []
    durations: list[float] = []
    keyed: list[tuple[str, float]] = []
    for s in steps:
        if s.error is not None:
            continue
        for path, leaf in walk(s.full_result):
            if COORDINATE_KEYS & set(path):
                continue
            key = path[-1] if path else ""
            if isinstance(leaf, bool):
                continue
            if key == "id" or key.endswith("_id"):
                if isinstance(leaf, (int, float)):
                    ids.append(float(leaf))  # only grounds a number written as an id ("route 27", "#27")
                continue
            if isinstance(leaf, (int, float)):
                plain.append(float(leaf))
                if key in KEY_FIELDS:
                    keyed.append((key, float(leaf)))
                if key == "duration_seconds":
                    durations.append(float(leaf))
                if key == "cumulative_drive_hours":
                    durations.append(float(leaf) * 3600)
            elif isinstance(leaf, str):
                # dates and timestamps are matched as dates, not as loose numbers
                plain.extend(float(m.group(0).replace(",", "")) for m in NUMBER.finditer(ISO_DATE.sub(" ", leaf)))
        # list lengths (number of routes, stops, POIs)
        for _, value in _lists(s.full_result):
            plain.append(float(len(value)))
    for p in prompts:
        plain.extend(float(m.group(0).replace(",", "")) for m in NUMBER.finditer(p))
    # leg durations and duration differences
    hours = sorted({v for k, v in keyed if k == "cumulative_drive_hours"})
    durations += [(b - a) * 3600 for a, b in zip(hours, hours[1:], strict=False)]
    secs = [v for k, v in keyed if k == "duration_seconds"]
    durations += [abs(a - b) for a in secs for b in secs if a != b]
    return plain, durations, keyed, ids


def _lists(value):
    """(key, list) for every list in a result, except coordinate arrays."""
    if isinstance(value, dict):
        for k, v in value.items():
            if k in COORDINATE_KEYS or k == "elevation_profile":
                continue
            if isinstance(v, list):
                yield k, v
            yield from _lists(v)
    elif isinstance(value, list):
        for v in value:
            yield from _lists(v)


def _tolerance(text: str) -> float:
    """Half a unit of the displayed precision; trailing zeros on whole numbers mean coarser rounding."""
    if "." in text:
        return 0.5 * 10 ** -len(text.split(".")[1]) + 1e-9
    digits = text.replace(",", "")
    zeros = len(digits) - len(digits.rstrip("0")) if digits.strip("0") else 0
    return 0.5 * 10 ** min(zeros, 2) + 1e-9


def _derived_values(keyed) -> list[tuple[str, float]]:
    out = []
    for name, fn in UNARY_DERIVATIONS.items():
        for k, v in keyed:
            r = fn(k, v)
            if r is not None:
                out.append((name, r))
    by_key: dict[str, list[float]] = {}
    for k, v in keyed:
        by_key.setdefault(k, []).append(v)
    for k, values in by_key.items():
        uniq = sorted(set(values))
        for a in uniq:
            for b in uniq:
                if a == b:
                    continue
                for name, fn in PAIR_DERIVATIONS.items():
                    if name.startswith("difference in") and k != "duration_seconds":
                        continue
                    r = fn(a, b)
                    if r is not None:
                        out.append((f"{name} of {k}", r))
    return out


def _date_strings(steps) -> set[tuple[int, int]]:
    found = set()
    for s in steps:
        if s.error is not None:
            continue
        for _, leaf in walk(s.full_result):
            if isinstance(leaf, str):
                for m in ISO_DATE.finditer(leaf):
                    found.add((int(m.group(2)), int(m.group(3))))
        for leaf in s.args.values():
            if isinstance(leaf, str):
                for m in ISO_DATE.finditer(leaf):
                    found.add((int(m.group(2)), int(m.group(3))))
    return found


def _sentence(text: str, start: int) -> str:
    left = max(text.rfind(".", 0, start), text.rfind("\n", 0, start)) + 1
    right_candidates = [i for i in (text.find(".", start), text.find("\n", start)) if i != -1]
    right = min(right_candidates) if right_candidates else len(text)
    return text[left:right].strip()[:160]


def numeric_grounding(session: Session) -> CheckResult:
    evidence: list[str] = []
    notes: list[str] = []
    for i, turn in enumerate(session.turns):
        steps = session_steps(session, i)
        prompts = [t.prompt for t in session.turns[: i + 1]]
        text = reply_text(turn)
        if turn.final_answer:
            dw = turn.final_answer.get("departure_window") or {}
            text = f"{text}\n{dw.get('start', '')}\n{dw.get('end', '')}"
        plain, durations, keyed, ids = _grounded_values(steps, prompts)
        derived = _derived_values(keyed)
        dates = _date_strings(steps)
        today = date.today()
        dates.add((today.month, today.day))  # "today" is always known to the agent

        consumed = [False] * len(text)

        def consume(m):
            for j in range(m.start(), m.end()):
                consumed[j] = True

        for m in ISO_DATE.finditer(text):
            if (int(m.group(2)), int(m.group(3))) not in dates:
                evidence.append(f"turn {i + 1}: date {m.group(0)!r} not in any tool result: {_sentence(text, m.start())!r}")
            consume(m)
        for m in NAMED_DATE.finditer(text):
            key = (MONTHS[m.group(1).lower()[:3]], int(m.group(2)))
            if key not in dates:
                evidence.append(f"turn {i + 1}: date {m.group(0)!r} not in any tool result: {_sentence(text, m.start())!r}")
            consume(m)
        for m in DAY_MONTH_DATE.finditer(text):
            key = (MONTHS[m.group(2).lower()[:3]], int(m.group(1)))
            if key not in dates:
                evidence.append(f"turn {i + 1}: date {m.group(0)!r} not in any tool result: {_sentence(text, m.start())!r}")
            consume(m)
        for m in SLASH_DATE.finditer(text):
            key = (int(m.group(1)), int(m.group(2)))
            if not (1 <= key[0] <= 12 and 1 <= key[1] <= 31):
                continue  # "50/50" is not a date; left for the number check
            if key not in dates:
                evidence.append(f"turn {i + 1}: date {m.group(0)!r} not in any tool result: {_sentence(text, m.start())!r}")
            consume(m)

        starts = " ".join(plan_starts_of(steps))
        for m in CLOCK_TIME.finditer(text):
            if any(consumed[m.start():m.end()]):
                continue
            hour = int(m.group(1) or m.group(4))
            minute = int(m.group(2) or m.group(5) or 0)
            suffix = (m.group(3) or "").lower().replace(".", "")
            if suffix == "pm" and hour < 12:
                hour += 12
            if suffix == "am" and hour == 12:
                hour = 0
            if f"T{hour:02d}:{minute:02d}" not in starts:
                evidence.append(f"turn {i + 1}: clock time {m.group(0)!r} not from plan_stops start: {_sentence(text, m.start())!r}")
            consume(m)

        for m in DURATION.finditer(text):
            if any(consumed[m.start():m.end()]):
                continue
            if m.group(3):
                seconds, tol = int(m.group(3)) * 60, 60.0
            else:
                hours_text = m.group(1)
                seconds = float(hours_text) * 3600 + (int(m.group(2)) * 60 if m.group(2) else 0)
                if m.group(2):
                    tol = 60.0
                elif "." in hours_text:
                    tol = 0.5 * 10 ** -len(hours_text.split(".")[1]) * 3600 + 1
                else:
                    tol = 1800.0
            if not any(abs(seconds - d) <= tol for d in durations):
                evidence.append(f"turn {i + 1}: duration {m.group(0)!r} matches no tool duration or documented derivation: {_sentence(text, m.start())!r}")
            consume(m)

        for m in ROAD_NAME.finditer(text):
            consume(m)

        for m in NUMBER.finditer(text):
            if any(consumed[m.start():m.end()]):
                continue
            shown = m.group(0)
            value = float(shown.replace(",", ""))
            tol = _tolerance(shown)
            if any(abs(value - v) <= tol for v in plain):
                continue
            if value in ids and ID_CONTEXT.search(text[max(0, m.start() - 12):m.start()]):
                continue
            via = next((name for name, v in derived if abs(abs(value) - abs(v)) <= tol), None)
            if via:
                notes.append(f"turn {i + 1}: {shown} grounded via {via}")
                continue
            evidence.append(f"turn {i + 1}: number {shown!r} not in any tool result or derivation: {_sentence(text, m.start())!r}")
    return CheckResult(not evidence, evidence, notes[:20])


# ---------------------------------------------------------------------------
# b. no_invented_scale
# ---------------------------------------------------------------------------

SCALE_PATTERNS = [
    re.compile(r"\b\d+(?:\.\d+)?\s*/\s*(?:100|10|5)\b"),
    re.compile(r"\bout of\s+(?:100|10|5|ten|five|a hundred)\b", re.I),
    re.compile(r"\bon a (?:\d+[- ]point |0[- ]?(?:to|-)[- ]?\d+ )?scale\b", re.I),
    re.compile(r"\bscen\w*\s+(?:score|rating|index)\s+(?:of\s+)?\d+(?:\.\d+)?\s*%", re.I),
]


def no_invented_scale(session: Session) -> CheckResult:
    evidence = []
    for i, turn in enumerate(session.turns):
        text = reply_text(turn)
        for pattern in SCALE_PATTERNS:
            for m in pattern.finditer(text):
                evidence.append(f"turn {i + 1}: {m.group(0)!r} in {_sentence(text, m.start())!r}")
    return CheckResult(not evidence, evidence)


# ---------------------------------------------------------------------------
# c. stops_grounded
# ---------------------------------------------------------------------------

# Heuristic for free text: a capitalised phrase after a stop/overnight cue.
# It cannot see stops named without one of these cues; README lists the limits.
# Place names must be capitalised; only the cue words are matched case-insensitively.
# Words of one name stay on one line (spaces only), so list items aren't joined across lines.
PLACE = r"((?:[A-Z][\w'’-]*)(?:(?:[ \t]+(?:of|de|del)[ \t]+|[ \t]+|[ \t]*/[ \t]*)[A-Z][\w'’-]*){0,3})"
STOP_PATTERNS = [
    # "stay overnight in X", "stop for lunch at X"
    re.compile(r"(?i:\b(?:stop|stops|stopping|overnight|night|nights|stay|staying|sleep|rest|break|lunch|dinner|"
               r"camp|camping|refuel)\b[^.\n]{0,40}?\b(?:in|at|near|around)\s+(?:the\s+)?)" + PLACE),
    # "Day 2: Austin -> X", "Night 1: X"
    re.compile(r"\b(?:Day|Night)\s+\d+\s*[:\-–—]\s*[^.\n]{0,40}?(?:→|->|–|—|\bto\b|\bin\b|\bat\b|:)\s*" + PLACE),
    re.compile(r"\b(?:Day|Night)\s+\d+\s*[:\-–—]\s*" + PLACE),
    # a list item or bold lead naming a place: "- **Gilroy, about 80 miles in:**", "- Hollister (mile 100):",
    # "- Lebec area:". A lead followed only by a colon ("**Dinner:**") is a label, not a place.
    re.compile(r"(?m)^\s*(?:[-*•]|\d+\.)?\s*(?:\*\*)?" + PLACE + r"(?:\s+area\b|\s*,|\s+\(|\s+[-–—]\s)"),
    # "the X area"
    re.compile(PLACE + r"\s+area\b"),
]
# Capitalised words that start list items or sentences but are not places
NOT_PLACES = {
    "day", "night", "the", "a", "an", "i", "you", "fastest", "backroads", "route", "routes", "highway", "interstate",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "today", "tomorrow",
    "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
    "december", "warnings", "warning", "summary", "departure", "note", "notes", "tip", "tips", "stops", "stop",
    "overnight", "weather", "forecast", "distance", "drive", "time", "scenic", "score", "climbing", "ascent", "trip",
    "option", "options", "recommendation", "why", "food", "fuel", "hotel", "hotels", "lodging", "other", "gas",
    "coffee", "restaurants", "restaurant", "attractions", "parks", "camping", "both", "if", "for", "at", "in", "on",
    "pros", "cons", "total", "leg", "legs", "arrival", "start", "end", "best", "yes", "no",
}


def _source_text(steps, prompts) -> str:
    parts = list(prompts)
    for tool in ("geocode_location", "plan_stops", "search_pois", "create_trip", "generate_routes"):
        for _, result in results(steps, tool):
            parts.append(json.dumps(result, default=str))
    return " ".join(parts).lower()


def stops_grounded(session: Session) -> CheckResult:
    evidence: list[str] = []
    notes: list[str] = []
    for i, turn in enumerate(session.turns):
        steps = session_steps(session, i)
        if turn.final_answer:
            ids = {str(s.get("id")) for s in plan_stops_of(steps)}
            for stop_id in turn.final_answer.get("stops") or []:
                if str(stop_id) not in ids:
                    evidence.append(f"turn {i + 1}: final_answer stop id {stop_id!r} is not a plan_stops id")
        text = reply_text(turn)
        sources = _source_text(steps, [t.prompt for t in session.turns[: i + 1]])
        seen = set()
        for pattern in STOP_PATTERNS:
            for m in pattern.finditer(text):
                name = m.group(1).strip(" .,'’")
                words = name.split()
                while words and words[0].lower() in NOT_PLACES:
                    words = words[1:]
                name = " ".join(words)
                if not name or name.lower() in NOT_PLACES or name in seen:
                    continue
                seen.add(name)
                if name.lower() in sources:
                    notes.append(f"turn {i + 1}: {name!r} grounded")
                else:
                    evidence.append(f"turn {i + 1}: stop {name!r} not from plan_stops, search_pois or geocode: {_sentence(text, m.start())!r}")
    return CheckResult(not evidence, evidence, notes)


# ---------------------------------------------------------------------------
# d. weather_on_arrival_dates
# ---------------------------------------------------------------------------

# Words that state conditions. "I can check the weather" is an offer, not a claim.
WEATHER_WORDS = re.compile(
    r"(\b(?:rain|rainy|showers?|drizzle|snow|snowy|storms?|thunderstorms?|sunny|clear sk(?:y|ies)|cloudy|"
    r"overcast|fog|foggy|chilly|highs?\s+(?:of|in|near|around)|lows?\s+(?:of|in|near|around)|"
    r"degrees|precipitation|chance of)\b|°)", re.I)


def weather_on_arrival_dates(session: Session) -> CheckResult:
    evidence: list[str] = []
    notes: list[str] = []
    for i, turn in enumerate(session.turns):
        steps = session_steps(session, i)
        turn_steps = turn.steps
        stops = plan_stops_of(steps)
        starts = plan_starts_of(steps)
        origin, destination = trip_endpoints(steps)
        dated_source = any(s.get("forecast") for s in stops)

        for s in turn_steps:
            if s.tool != "get_weather_forecast" or s.error is not None:
                continue
            lat, lon = s.args.get("lat"), s.args.get("lon")
            target = s.args.get("target_date")
            if lat is None or lon is None:
                continue
            near_stop = min(stops, key=lambda st: haversine_km(lat, lon, st["lat"], st["lon"]), default=None)
            if near_stop and haversine_km(lat, lon, near_stop["lat"], near_stop["lon"]) <= NEAR_KM:
                expected, what = near_stop.get("arrival_date"), f"stop {near_stop.get('name') or near_stop.get('id')}"
            elif destination and haversine_km(lat, lon, *destination) <= NEAR_KM:
                expected = next((st.get("arrival_date") for st in stops if st.get("kind") == "destination"), None)
                what = "the destination"
            elif origin and haversine_km(lat, lon, *origin) <= NEAR_KM:
                expected = starts[-1][:10] if starts else None
                what = "the origin (departure date)"
            else:
                notes.append(f"turn {i + 1}: weather call at {lat},{lon} is not near the origin, a stop or the destination")
                continue
            if expected is None:
                evidence.append(f"turn {i + 1}: weather for {what} requested with no plan_stops arrival date to judge it by (args {s.args})")
            elif target != expected:
                evidence.append(f"turn {i + 1}: weather for {what} used target_date={target!r}, arrival date is {expected!r}")
            else:
                dated_source = True

        text = reply_text(turn)
        m = WEATHER_WORDS.search(text)
        if m and not dated_source:
            evidence.append(f"turn {i + 1}: reply talks about weather with no arrival-dated forecast behind it: {_sentence(text, m.start())!r}")
    return CheckResult(not evidence, evidence, notes)


# ---------------------------------------------------------------------------
# e. poi_coords_grounded
# ---------------------------------------------------------------------------


def poi_coords_grounded(session: Session) -> CheckResult:
    evidence: list[str] = []
    notes: list[str] = []
    for i, turn in enumerate(session.turns):
        steps = session_steps(session, i)
        points = [(r["lat"], r["lon"]) for _, r in results(steps, "geocode_location")
                  if isinstance(r, dict) and "lat" in r]
        points += [(st["lat"], st["lon"]) for st in plan_stops_of(steps)]
        routes = routes_of(steps)
        selected_ids = {s.args.get("route_id") for s in steps if s.tool == "select_route" and s.error is None}
        selected = [r for r in routes if r.get("id") in selected_ids] or routes
        lines = [route_coords(r) for r in selected]
        for s in turn.steps:
            if s.tool != "search_pois" or s.error is not None:
                continue
            lat, lon = s.args.get("lat"), s.args.get("lon")
            near_point = min((haversine_km(lat, lon, a, b) for a, b in points), default=math.inf)
            near_route = min((distance_to_line_km(lat, lon, c) for c in lines), default=math.inf)
            if min(near_point, near_route) <= NEAR_KM:
                notes.append(f"turn {i + 1}: search_pois at {lat},{lon} is {min(near_point, near_route):.1f} km from a grounded point")
            else:
                evidence.append(
                    f"turn {i + 1}: search_pois at {lat},{lon} is {near_point:.0f} km from any geocode/plan_stops point "
                    f"and {near_route:.0f} km from the route")
    return CheckResult(not evidence, evidence, notes)


# ---------------------------------------------------------------------------
# f. no_duplicate_work
# ---------------------------------------------------------------------------


def _canonical(args: dict) -> str:
    return json.dumps(args, sort_keys=True, default=str)


def no_duplicate_work(session: Session) -> CheckResult:
    evidence: list[str] = []
    trips: dict[tuple, int] = {}
    for i, turn in enumerate(session.turns):
        seen: dict[tuple, int] = {}
        for s in executed(turn.steps):
            key = (s.tool, _canonical(s.args))
            seen[key] = seen.get(key, 0) + 1
            if seen[key] == 2:
                evidence.append(f"turn {i + 1}: {s.tool} executed twice with identical args {s.args}")
            if s.tool == "create_trip":
                a = s.args
                pair = tuple(round(float(a.get(k, 0)), 2) for k in ("origin_lat", "origin_lon", "destination_lat", "destination_lon"))
                trips[pair] = trips.get(pair, 0) + 1
                if trips[pair] == 2:
                    evidence.append(f"turn {i + 1}: create_trip called again for the same origin/destination {pair}")
    return CheckResult(not evidence, evidence)


# ---------------------------------------------------------------------------
# g. concise_reply
# ---------------------------------------------------------------------------

MAX_WORDS = 150
EMOJI = re.compile("[\U0001F300-\U0001FAFF\U0001F000-\U0001F2FF☀-➿⭐⭕️]")
TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.M)


def surface_stats(text: str) -> dict:
    return {
        "word_count": len(re.findall(r"[\w'’-]+", text)),
        "has_emoji": bool(EMOJI.search(text)),
        "has_table": len(TABLE_ROW.findall(text)) >= 2,
    }


def concise_reply(session: Session, judge: Callable[[str], dict[str, Any]]) -> CheckResult:
    evidence: list[str] = []
    notes: list[str] = []
    for i, turn in enumerate(session.turns):
        text = reply_text(turn)
        stats = surface_stats(text)
        verdict = judge(text)
        deterministic_ok = stats["word_count"] < MAX_WORDS and not stats["has_emoji"] and not stats["has_table"]
        notes.append(f"turn {i + 1}: counted {stats}; judge {verdict}")
        if not deterministic_ok or not verdict.get("pass"):
            evidence.append(
                f"turn {i + 1}: {stats['word_count']} words, emoji={stats['has_emoji']}, table={stats['has_table']}; "
                f"judge: {verdict.get('reason')!r}")
    return CheckResult(not evidence, evidence, notes)


CHECKS = {
    "numeric_grounding": numeric_grounding,
    "no_invented_scale": no_invented_scale,
    "stops_grounded": stops_grounded,
    "weather_on_arrival_dates": weather_on_arrival_dates,
    "poi_coords_grounded": poi_coords_grounded,
    "no_duplicate_work": no_duplicate_work,
    "concise_reply": concise_reply,
}
