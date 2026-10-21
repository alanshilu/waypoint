"""
The trip agent's loop: the model asks for tools, the tools run, until it gives its structured final answer.
Agent is built from what it needs (model clients, a tool registry, the prompt and model settings), so a
fake client or a different set of tools needs no change here. get_agent wires the app's defaults.
"""

from __future__ import annotations

import copy
import json
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Protocol

import anthropic

from app.agent.answer import FINAL_ANSWER_SCHEMA, parse_final_answer, refusal_answer, render_reply
from app.agent.model_view import model_view, truncate
from app.agent.prompt import SYSTEM_PROMPT
from app.core.config import settings

MAX_TOKENS = 16000
# A runaway loop is a bug; stop instead of spending.
MAX_MODEL_CALLS_PER_TURN = 20
# Server-side refusal fallback: a declined request is re-run on Anthropic's
# recommended fallback model inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass
class Step:
    """One tool call made during an agent turn."""

    tool: str
    args: dict
    ms: int
    result: str | None = None  # JSON, truncated to model_view.TRACE_RESULT_LIMIT characters
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


class ModelClients(Protocol):
    """Model clients for a turn: the server's, or one on a user's own key that lives only for that turn."""

    def open(self, api_key: str | None) -> Any:
        """A context manager giving a client with .beta.messages.create(...)."""
        ...


class AnthropicClients:
    """
    The server's Anthropic client (made once, on first use) and, for bring your own key, a new client per turn
    that is closed, and dropped with the key, when the turn ends.
    """

    def __init__(self, server_api_key: str | None, make_client: Callable[[str], Any] = anthropic.Anthropic):
        self._server_api_key = server_api_key
        self._make_client = make_client
        self._server = None

    @property
    def server(self):
        if self._server is None:
            self._server = self._make_client(api_key=self._server_api_key)
        return self._server

    @contextmanager
    def open(self, api_key: str | None) -> Iterator[Any]:
        if api_key is None:
            yield self.server
            return
        with self._make_client(api_key=api_key) as own:
            yield own


def _cache_key(name: str, args: dict) -> str:
    return name + ":" + json.dumps(args, sort_keys=True, default=str)


def _call_tokens(usage) -> dict:
    return {
        "input": usage.input_tokens or 0,
        "output": usage.output_tokens or 0,
        "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
        "cache_write": getattr(usage, "cache_creation_input_tokens", 0) or 0,
    }


class Agent:
    def __init__(self, clients: ModelClients, tools: Mapping[str, Callable[..., Any]], tool_schemas: list[dict], *,
                 system_prompt: str = SYSTEM_PROMPT, model: str | None = None, effort: str | None = None):
        self.clients = clients
        self.tools = tools
        self.tool_schemas = tool_schemas
        self.system_prompt = system_prompt
        self.model = model or settings.agent_model
        self.effort = effort or settings.agent_effort

    def run(self, conversation_history: list, user_message: str,
            on_event: Callable[[dict], None] | None = None, api_key: str | None = None) -> AgentTurn:
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
        with self.clients.open(api_key) as client:
            return self._run_turn(client, conversation_history, user_message, on_event or (lambda event: None))

    def _run_tool(self, name: str, args: dict) -> tuple[Any, str | None]:
        func = self.tools.get(name)
        if func is None:
            return None, f"Unknown tool {name!r}; available: {', '.join(sorted(self.tools))}"
        try:
            return func(**args), None
        except Exception as e:  # noqa: BLE001 - reported to the model as a tool error
            return None, f"{type(e).__name__}: {e}"

    def _run_turn(self, client, conversation_history: list, user_message: str, emit: Callable[[dict], None]) -> AgentTurn:
        messages = conversation_history + [{"role": "user", "content": user_message}]
        steps: list[Step] = []
        usage = Usage(model=self.model)
        # (tool, args) -> (model-visible content, full result, error): identical calls in a turn run once
        cache: dict[str, tuple[str, Any, str | None]] = {}

        for model_call in range(MAX_MODEL_CALLS_PER_TURN):
            response = client.beta.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=self.system_prompt,
                tools=self.tool_schemas,
                messages=messages,
                output_config={
                    "effort": self.effort,
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
                answer = refusal_answer(category)
                return AgentTurn(render_reply(answer), messages, steps, usage, answer)

            if response.stop_reason != "tool_use":
                text = "".join(block.text for block in response.content if block.type == "text")
                answer = parse_final_answer(text, response.stop_reason)
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
                    result, error = self._run_tool(block.name, args)
                    content = (json.dumps(model_view(result), default=str) if error is None
                               else f"Error calling {block.name}: {error}")
                    cache[key] = (content, result, error)
                content, result, error = cache[key]
                step = Step(
                    tool=block.name, args=args, ms=round((time.perf_counter() - started) * 1000),
                    result=None if error else truncate(json.dumps(result, default=str)),
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


@lru_cache(maxsize=1)
def get_agent() -> Agent:
    """The app's agent: Anthropic, on the server's key, with every tool in app/agent/tools. The FastAPI dependency."""
    from app.agent.tools import TOOL_FUNCTIONS, TOOL_SCHEMAS

    return Agent(AnthropicClients(settings.anthropic_api_key), TOOL_FUNCTIONS, TOOL_SCHEMAS)


def run_agent_turn(conversation_history: list, user_message: str,
                   on_event: Callable[[dict], None] | None = None, api_key: str | None = None) -> AgentTurn:
    """Agent.run with the app's agent (for scripts and the evals)."""
    return get_agent().run(conversation_history, user_message, on_event, api_key)


if __name__ == "__main__":
    turn = run_agent_turn([], "I want the fastest route from Austin, TX to San Francisco, CA. Also select the fastest route and give me any POIs along the way.Also tell what would be the best time to leave and what is the weather like in Austin, TX and San Francisco, CA.")
    print(turn.reply)
    print(json.dumps(turn.final_answer, indent=2))
    print()
    for step in turn.steps:
        print(f"{step.tool:24} {step.ms:>6} ms  {'cached ' if step.cached else ''}{step.error or ''}")
    print(turn.usage.to_dict())
