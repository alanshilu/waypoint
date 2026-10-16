import json
import anthropic
from app.core.config import settings
from app.agent.prompt import SYSTEM_PROMPT
from app.agent.tools import TOOL_SCHEMAS, TOOL_FUNCTIONS

client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

MODEL = "claude-sonnet-4-6"  # confirm the current recommended string at docs.claude.com


def run_agent_turn(conversation_history, user_message):
    """
    conversation_history: list of prior {"role": ..., "content": ...} messages
    user_message: the new user message (string)

    Returns (reply_text, updated_history) -- store updated_history and pass
    it back in on the next call so the agent keeps context across turns.
    """
    messages = conversation_history + [{"role": "user", "content": user_message}]

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            reply_text = "".join(
                block.text for block in response.content if block.type == "text"
            )
            return reply_text, messages

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            func = TOOL_FUNCTIONS[block.name]
            try:
                result = func(**block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, default=str),
                })
            except Exception as e:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"Error calling {block.name}: {e}",
                    "is_error": True,
                })

        messages.append({"role": "user", "content": tool_results})


if __name__ == "__main__":
    history = []
    reply, history = run_agent_turn(history, "I want the fastest route from Austin, TX to San Francisco, CA. Also select the fastest route and give me any POIs along the way.Also tell what would be the best time to leave and what is the weather like in Austin, TX and San Francisco, CA.")
    print(reply)
