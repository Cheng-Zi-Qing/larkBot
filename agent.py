from __future__ import annotations

from collections import defaultdict

import config
import hooks
import llm
import logger
from hooks import HookContext
from tools import execute_tool, get_tool_definitions

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

    client = llm.get_client()

    for _ in range(config.MAX_AGENT_ROUNDS):
        response = client.chat(
            messages=messages,
            system=config.SYSTEM_PROMPT,
            tools=get_tool_definitions(),
            model=config.LLM_MODEL,
        )

        messages.append(client.build_assistant_message(response))

        if response.stop_reason == "end_turn":
            reply_text = response.text or ""

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
            tool_use_results = []
            for tc in response.tool_calls:
                result = execute_tool(request_id, tc.name, tc.input)
                tool_use_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": result.output,
                    "is_error": not result.success,
                })

            built = client.build_tool_results(tool_use_results)
            if isinstance(built, list):
                messages.extend(built)
            else:
                messages.append(built)

    return "处理轮数超限，请简化你的请求。"
