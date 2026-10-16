import json
import time
from dataclasses import dataclass, field
from typing import Any

import anthropic

from app.agent.prompt import SYSTEM_PROMPT
from app.agent.tools import TOOL_FUNCTIONS, TOOL_SCHEMAS
from app.core.config import settings

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

MAX_TOKENS = 16000
# Size limit for a step's result in the trace. The full result stays on the
# step in memory (full_result) so eval checks can read all of it.
TRACE_RESULT_LIMIT = 4000


@dataclass
class Step:
    """One tool call made during an agent turn."""

    tool: str
    args: dict
    ms: int
    result: str | None = None  # JSON, truncated to TRACE_RESULT_LIMIT characters
    error: str | None = None
    full_result: Any = field(default=None, repr=False)

    def to_dict(self) -> dict:
        return {"tool": self.tool, "args": self.args, "result": self.result, "ms": self.ms, "error": self.error}


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
    reply: str
    messages: list  # full history; pass back in on the next turn
    steps: list[Step]
    usage: Usage


def _truncate(text: str, limit: int = TRACE_RESULT_LIMIT) -> str:
    return text if len(text) <= limit else text[:limit] + f"... [truncated, {len(text)} chars]"


def run_agent_turn(conversation_history: list, user_message: str) -> AgentTurn:
    """
    conversation_history: list of prior {"role": ..., "content": ...} messages
    user_message: the new user message (string)

    Returns an AgentTurn. Pass turn.messages back in as conversation_history on
    the next call so the agent keeps context across turns.
    """
    messages = conversation_history + [{"role": "user", "content": user_message}]
    steps: list[Step] = []
    usage = Usage(model=settings.agent_model)

    while True:
        response = client.messages.create(
            model=settings.agent_model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )
        usage.add(response.usage)

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            reply_text = "".join(
                block.text for block in response.content if block.type == "text"
            )
            return AgentTurn(reply=reply_text, messages=messages, steps=steps, usage=usage)

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            started = time.perf_counter()
            func = TOOL_FUNCTIONS[block.name]
            try:
                result = func(**block.input)
                content = json.dumps(result, default=str)
                steps.append(Step(
                    tool=block.name, args=dict(block.input), ms=round((time.perf_counter() - started) * 1000),
                    result=_truncate(content), full_result=result,
                ))
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                })
            except Exception as e:
                steps.append(Step(
                    tool=block.name, args=dict(block.input), ms=round((time.perf_counter() - started) * 1000),
                    error=f"{type(e).__name__}: {e}",
                ))
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"Error calling {block.name}: {e}",
                    "is_error": True,
                })

        messages.append({"role": "user", "content": tool_results})


if __name__ == "__main__":
    turn = run_agent_turn([], "I want the fastest route from Austin, TX to San Francisco, CA. Also select the fastest route and give me any POIs along the way.Also tell what would be the best time to leave and what is the weather like in Austin, TX and San Francisco, CA.")
    print(turn.reply)
    print()
    for step in turn.steps:
        print(f"{step.tool:24} {step.ms:>6} ms  {step.error or ''}")
    print(turn.usage.to_dict())
