from __future__ import annotations

from collections import defaultdict

import anthropic

import config
import hooks
import logger
from hooks import HookContext
from tools import execute_tool, get_tool_definitions

client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

history: dict[str, list[dict]] = defaultdict(list)


def _trim_history(chat_id: str):
    msgs = history[chat_id]
    if len(msgs) > config.MAX_HISTORY * 2:
        history[chat_id] = msgs[-(config.MAX_HISTORY * 2):]


def run(request_id: str, chat_id: str, user_message: str) -> str:
    hooks.fire("on_message_in", HookContext(request_id=request_id, chat_id=chat_id))

    messages = list(history.get(chat_id, []))
    messages.append({"role": "user", "content": user_message})

    hooks.fire("before_agent", HookContext(request_id=request_id, messages=messages))

    for _ in range(config.MAX_AGENT_ROUNDS):
        response = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=4096,
            system=config.SYSTEM_PROMPT,
            tools=get_tool_definitions(),
            messages=messages,
        )

        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        if response.stop_reason == "end_turn":
            reply_text = next(
                (b.text for b in assistant_content if hasattr(b, "text")), ""
            )

            hook_result = hooks.fire(
                "on_reply",
                HookContext(request_id=request_id, reply_text=reply_text),
            )
            if hook_result.override_output:
                reply_text = hook_result.override_output

            logger.log_conversation(request_id, chat_id, user_message, messages, reply_text)
            history[chat_id] = messages
            _trim_history(chat_id)
            return reply_text

        elif response.stop_reason == "tool_use":
            tool_results = []
            for block in assistant_content:
                if block.type == "tool_use":
                    result = execute_tool(request_id, block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result.output,
                        "is_error": not result.success,
                    })
            messages.append({"role": "user", "content": tool_results})

    return "处理轮数超限，请简化你的请求。"
