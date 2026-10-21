"""A conversation's Messages API history: stored as plain JSON, trimmed to the recent turns."""

from __future__ import annotations

from typing import Any

THINKING_TYPES = {"thinking", "redacted_thinking"}


def to_jsonable(messages: list) -> list[dict]:
    """History as plain JSON: SDK content blocks become dicts the API accepts back unchanged."""
    out = []
    for message in messages:
        content = message["content"]
        if isinstance(content, list):
            content = [
                block.model_dump(mode="json", exclude_none=True) if hasattr(block, "model_dump") else block
                for block in content
            ]
        out.append({"role": message["role"], "content": content})
    return out


def _is_user_text(message: dict) -> bool:
    """A turn the user typed, as opposed to a user message carrying tool results."""
    content = message["content"]
    return message["role"] == "user" and (
        isinstance(content, str) or not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
    )


def trim_history(messages: list[dict], max_turns: int) -> list[dict]:
    """
    Keeps the last max_turns user turns, cutting only at a typed user message so
    tool_use / tool_result pairs stay together.

    When anything is cut, thinking blocks are also removed from what remains.
    A Claude thinking block is signed against every message before it, so after
    the front of the history changes those blocks would fail validation. Without
    them the request stays valid; the model only loses its earlier reasoning.
    """
    starts = [i for i, m in enumerate(messages) if _is_user_text(m)]
    if len(starts) <= max_turns:
        return messages
    kept = messages[starts[-max_turns]:]
    trimmed = []
    for message in kept:
        content: Any = message["content"]
        if message["role"] == "assistant" and isinstance(content, list):
            content = [b for b in content if not (isinstance(b, dict) and b.get("type") in THINKING_TYPES)]
            if not content:
                continue
        trimmed.append({"role": message["role"], "content": content})
    return trimmed
