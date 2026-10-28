"""
Prompt injection for the evals: plants a case's text in what the agent's tools return, the way a hostile
OpenStreetMap name or description would arrive. A case in cases.json sets

    "inject": {"tools": ["plan_stops", "find_places"], "text": "...", "canary": "MARMALADE"}

and the runner wraps those tools: their real result comes back with the text appended to the name (and the
facts, where there are any) of the first item of every list of places, POIs or stops in it.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from typing import Any

# Lists whose items are named places: find_places groups' places, search_pois pois, plan_stops stops
PLACE_LISTS = ("places", "pois", "stops", "lunch_stops")


def plant(result: Any, text: str) -> Any:
    """A copy of result with text planted in the first named item of each place list."""
    out = copy.deepcopy(result)

    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in PLACE_LISTS and isinstance(child, list) and child and isinstance(child[0], dict):
                    first = child[0]
                    if isinstance(first.get("name"), str):
                        first["name"] = f"{first['name']} ({text})"
                    if isinstance(first.get("facts"), list):
                        first["facts"].append(text)
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(out)
    return out


def with_injection(tools: Mapping[str, Callable[..., Any]], inject: dict) -> dict[str, Callable[..., Any]]:
    """The agent's tools, with inject["tools"] returning their results with inject["text"] planted."""
    wrapped = dict(tools)
    for name in inject.get("tools") or []:
        real = tools[name]

        def planted(*args, _real=real, **kwargs):
            return plant(_real(*args, **kwargs), inject["text"])

        wrapped[name] = planted
    return wrapped
