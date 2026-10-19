import copy
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

import anthropic

from app.agent.prompt import SYSTEM_PROMPT
from app.agent.tools import TOOL_FUNCTIONS, TOOL_SCHEMAS
from app.core.config import settings

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)


def make_client(api_key: str) -> anthropic.Anthropic:
    """A client for one turn on a user's own key (bring your own key). The key lives only in this object."""
    return anthropic.Anthropic(api_key=api_key)

MAX_TOKENS = 16000
# Size limit for a step's result in the trace. The full result stays on the
# step in memory (full_result) so eval checks can read all of it.
TRACE_RESULT_LIMIT = 4000
# A runaway loop is a bug; stop instead of spending.
MAX_MODEL_CALLS_PER_TURN = 20
# Server-side refusal fallback: a declined request is re-run on Anthropic's
# recommended fallback model inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# The structured final answer. output_config.format guarantees that every
# response that ends the turn is JSON matching this schema.
FINAL_ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "recommended_route_type": {"type": "string", "enum": ["fastest", "backroads", "none"]},
        "departure_window": {
            "type": "object",
            "properties": {
                "start": {"type": "string", "description": "ISO 8601 date-time, or empty"},
                "end": {"type": "string", "description": "ISO 8601 date-time, or empty"},
                "reason": {"type": "string"},
            },
            "required": ["start", "end", "reason"],
            "additionalProperties": False,
        },
        "stops": {"type": "array", "items": {"type": "string"}, "description": "plan_stops stop ids"},
        "places": {
            "type": "array",
            "description": "recommended find_places places",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["id", "reason"],
                "additionalProperties": False,
            },
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "recommended_route_type", "departure_window", "stops", "places", "warnings"],
    "additionalProperties": False,
}


@dataclass
class Step:
    """One tool call made during an agent turn."""

    tool: str
    args: dict
    ms: int
    result: str | None = None  # JSON, truncated to TRACE_RESULT_LIMIT characters
    error: str | None = None
    cached: bool = False  # served from this turn's cache; the tool did not run again
    # Tokens of the model call that requested this tool. Tool calls made in the
    # same model response share that call (same model_call index).
    tokens: dict | None = None
    model_call: int = 0
    full_result: Any = field(default=None, repr=False)

    def to_dict(self) -> dict:
        return {"tool": self.tool, "args": self.args, "result": self.result, "ms": self.ms, "error": self.error,
                "cached": self.cached, "tokens": self.tokens, "model_call": self.model_call}


@dataclass
class Usage:
    """Token counts summed over every model call in a turn."""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    requests: int = 0

    def add(self, usage) -> None:
        self.input_tokens += usage.input_tokens or 0
        self.output_tokens += usage.output_tokens or 0
        self.cache_creation_input_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.cache_read_input_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.requests += 1

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class AgentTurn:
    reply: str  # what a user sees: rendered from final_answer
    messages: list  # full history; pass back in on the next turn
    steps: list[Step]
    usage: Usage
    final_answer: dict | None = None


def _truncate(text: str, limit: int = TRACE_RESULT_LIMIT) -> str:
    return text if len(text) <= limit else text[:limit] + f"... [truncated, {len(text)} chars]"


def model_view(result: Any) -> Any:
    """
    The tool result as the model sees it. Route geometry and elevation samples
    are replaced by short summaries: the model never needs hundreds of
    coordinates (plan_stops gives it the points it may use), and they would be
    re-sent on every loop iteration. The trace keeps the full result.
    """
    if isinstance(result, dict):
        out = {}
        for key, value in result.items():
            if key == "geometry" and isinstance(value, dict) and "coordinates" in value:
                out[key] = {"type": value.get("type"), "points": len(value["coordinates"])}
            elif key == "elevation_profile" and isinstance(value, list) and value:
                metres = [p.get("m") for p in value if isinstance(p, dict) and p.get("m") is not None]
                out[key] = {"samples": len(value), "min_m": min(metres, default=None), "max_m": max(metres, default=None)}
            else:
                out[key] = model_view(value)
        return out
    if isinstance(result, list):
        return [model_view(v) for v in result]
    return result


def _cache_key(name: str, args: dict) -> str:
    return name + ":" + json.dumps(args, sort_keys=True, default=str)


def _format_when(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%b %d %H:%M").replace(" 0", " ")
    except ValueError:
        return value


def render_reply(answer: dict) -> str:
    """The text a user reads. Departure times live in the structured field; the app shows them."""
    parts = [answer.get("summary", "").strip()]
    window = answer.get("departure_window") or {}
    if window.get("reason"):
        parts.append(f"Departure: {window['reason'].strip()}")
    for warning in answer.get("warnings") or []:
        parts.append(f"Note: {warning.strip()}")
    return "\n\n".join(p for p in parts if p)


def _run_tool(name: str, args: dict) -> tuple[Any, str | None]:
    func = TOOL_FUNCTIONS.get(name)
    if func is None:
        return None, f"Unknown tool {name!r}; available: {', '.join(sorted(TOOL_FUNCTIONS))}"
    try:
        return func(**args), None
    except Exception as e:  # noqa: BLE001 - reported to the model as a tool error
        return None, f"{type(e).__name__}: {e}"


def _call_tokens(usage) -> dict:
    return {
        "input": usage.input_tokens or 0,
        "output": usage.output_tokens or 0,
        "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
        "cache_write": getattr(usage, "cache_creation_input_tokens", 0) or 0,
    }


def run_agent_turn(
    conversation_history: list,
    user_message: str,
    on_event: Callable[[dict], None] | None = None,
    api_key: str | None = None,
) -> AgentTurn:
    """
    conversation_history: list of prior {"role": ..., "content": ...} messages
    user_message: the new user message (string)
    on_event: optional callback for live progress, called from this thread with
        {"type": "tool_start", "tool", "args"} before each tool call and
        {"type": "tool_end", "tool", "ms", "error", "cached", "tokens"} after it.
    api_key: a user's own Anthropic key for this turn only; None uses the server's key.

    Returns an AgentTurn. Pass turn.messages back in as conversation_history on
    the next call so the agent keeps context across turns.
    """
    if api_key is None:
        return _run_turn(client, conversation_history, user_message, on_event)
    with make_client(api_key) as own_client:  # closed, and dropped with the key, when the turn ends
        return _run_turn(own_client, conversation_history, user_message, on_event)


def _run_turn(
    api: anthropic.Anthropic,
    conversation_history: list,
    user_message: str,
    on_event: Callable[[dict], None] | None,
) -> AgentTurn:
    messages = conversation_history + [{"role": "user", "content": user_message}]
    steps: list[Step] = []
    usage = Usage(model=settings.agent_model)
    # (tool, args) -> (model-visible content, full result, error): identical calls in a turn run once
    cache: dict[str, tuple[str, Any, str | None]] = {}
    emit = on_event or (lambda event: None)

    for model_call in range(MAX_MODEL_CALLS_PER_TURN):
        response = api.beta.messages.create(
            model=settings.agent_model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
            output_config={
                "effort": settings.agent_effort,
                "format": {"type": "json_schema", "schema": FINAL_ANSWER_SCHEMA},
            },
            cache_control={"type": "ephemeral"},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
        usage.add(response.usage)
        call_tokens = _call_tokens(response.usage)
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "refusal":
            category = getattr(response.stop_details, "category", None) if response.stop_details else None
            answer = {"summary": "I can't help with that request.", "recommended_route_type": "none",
                      "departure_window": {"start": "", "end": "", "reason": ""}, "stops": [], "places": [],
                      "warnings": [f"The model declined this request ({category or 'no category'})."]}
            return AgentTurn(render_reply(answer), messages, steps, usage, answer)

        if response.stop_reason != "tool_use":
            text = "".join(block.text for block in response.content if block.type == "text")
            try:
                answer = json.loads(text)
            except json.JSONDecodeError:
                # only reachable on max_tokens, where the JSON can be cut off
                answer = {"summary": text, "recommended_route_type": "none",
                          "departure_window": {"start": "", "end": "", "reason": ""}, "stops": [], "places": [],
                          "warnings": [f"The answer was cut off (stop_reason={response.stop_reason})."]}
            return AgentTurn(render_reply(answer), messages, steps, usage, answer)

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            args = dict(block.input)
            key = _cache_key(block.name, args)
            emit({"type": "tool_start", "tool": block.name, "args": args})
            started = time.perf_counter()
            hit = key in cache
            if not hit:
                result, error = _run_tool(block.name, args)
                content = (json.dumps(model_view(result), default=str) if error is None
                           else f"Error calling {block.name}: {error}")
                cache[key] = (content, result, error)
            content, result, error = cache[key]
            step = Step(
                tool=block.name, args=args, ms=round((time.perf_counter() - started) * 1000),
                result=None if error else _truncate(json.dumps(result, default=str)),
                error=error, cached=hit, tokens=call_tokens, model_call=model_call,
                full_result=copy.deepcopy(result),
            )
            steps.append(step)
            emit({"type": "tool_end", "tool": step.tool, "ms": step.ms, "error": step.error,
                  "cached": step.cached, "tokens": step.tokens, "model_call": model_call})
            entry = {"type": "tool_result", "tool_use_id": block.id, "content": content}
            if error:
                entry["is_error"] = True
            tool_results.append(entry)

        messages.append({"role": "user", "content": tool_results})

    raise RuntimeError(f"Agent made {MAX_MODEL_CALLS_PER_TURN} model calls without finishing the turn")


if __name__ == "__main__":
    turn = run_agent_turn([], "I want the fastest route from Austin, TX to San Francisco, CA. Also select the fastest route and give me any POIs along the way.Also tell what would be the best time to leave and what is the weather like in Austin, TX and San Francisco, CA.")
    print(turn.reply)
    print(json.dumps(turn.final_answer, indent=2))
    print()
    for step in turn.steps:
        print(f"{step.tool:24} {step.ms:>6} ms  {'cached ' if step.cached else ''}{step.error or ''}")
    print(turn.usage.to_dict())
