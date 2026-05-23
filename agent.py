from __future__ import annotations

import json
import threading
from collections import defaultdict

import config
import hooks
import llm
import logger
import memory
import workflows
from hooks import HookContext
from tools import execute_tool, get_tool_definitions

history: dict[str, list[dict]] = defaultdict(list)
_history_lock = threading.Lock()


def _trim_history(chat_id: str):
    msgs = history[chat_id]
    if len(msgs) > config.MAX_HISTORY * 2:
        history[chat_id] = msgs[-(config.MAX_HISTORY * 2):]


def _sanitize_messages(messages: list[dict]) -> list[dict]:
    """Strip tool_use/tool_result blocks from restored history.

    Serialized SDK objects rarely round-trip cleanly, and an orphaned
    tool_use without its matching tool_result causes a 400 from the API.
    Keeping only text blocks is safe — the LLM loses tool context from
    prior turns but can still continue the conversation.
    """
    clean: list[dict] = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "assistant" and isinstance(content, list):
            text_blocks = [
                b for b in content
                if isinstance(b, dict) and b.get("type") == "text" and b.get("text")
            ]
            if text_blocks:
                clean.append({"role": "assistant", "content": text_blocks})
            elif any(isinstance(b, dict) and b.get("type") == "text" for b in content):
                pass
            else:
                continue

        elif role == "user" and isinstance(content, list):
            has_tool_result = any(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in content
            )
            if has_tool_result:
                continue
            clean.append(msg)

        elif role in ("user", "assistant"):
            clean.append(msg)

    return clean



def run(request_id: str, chat_id: str, user_message: str, sender_id: str = "",
        on_progress=None, on_plan=None) -> str:
    hooks.fire("on_message_in", HookContext(request_id=request_id, chat_id=chat_id))

    rotated = memory.check_session_boundary()
    session_id = memory.get_current_session_id()

    with _history_lock:
        if rotated:
            history[chat_id] = []
        if not history.get(chat_id):
            history[chat_id] = _sanitize_messages(memory.load_session_messages(session_id))
        messages = list(history.get(chat_id, []))

    hooks.fire("before_agent", HookContext(request_id=request_id, messages=messages))

    messages.append({"role": "user", "content": user_message})
    memory.persist_message(session_id, "user", user_message)

    try:
        return _agent_loop(request_id, chat_id, sender_id, session_id, user_message,
                           messages, on_progress, on_plan)
    except Exception as e:
        if "bad" not in type(e).__name__.lower():
            raise
        logger.log_error(request_id, "agent", "BadRequest_retry", stderr=str(e))
        with _history_lock:
            history[chat_id] = []
        messages = [{"role": "user", "content": user_message}]
        try:
            return _agent_loop(request_id, chat_id, sender_id, session_id, user_message,
                               messages, on_progress, on_plan)
        except Exception as e2:
            if "content-blocked" not in str(e2) and "content_blocked" not in str(e2):
                raise
            logger.log_error(request_id, "agent", "ContentBlocked_fallback", stderr=str(e2))
            client = llm.get_client()
            wf_ctx = ""
            wf_fallback = workflows.match(user_message, config.get_persona())
            if wf_fallback:
                wf_ctx = workflows.build_workflow_context(wf_fallback, user_message)
            resp = client.chat(
                messages=[{"role": "user", "content": user_message}],
                system=config.get_rich_system_prompt(wf_ctx),
                tools=[],
                model=config.LLM_MODEL,
            )
            return resp.text or "抱歉，处理遇到问题，请稍后重试。"


def _agent_loop(
    request_id: str,
    chat_id: str,
    sender_id: str,
    session_id: str,
    user_message: str,
    messages: list[dict],
    on_progress=None,
    on_plan=None,
) -> str:
    client = llm.get_client()
    collected_text: list[str] = []
    step_counter = 0
    total_steps = 0
    plan_steps: list[str] = []
    fail_counts: dict[str, int] = {}

    # Workflow matching: inject steps/template into system prompt if matched
    workflow_context = ""
    wf = workflows.match(user_message, config.get_persona())
    if wf:
        workflow_context = workflows.build_workflow_context(wf, user_message)
    system_prompt = config.get_rich_system_prompt(workflow_context)

    for _ in range(config.MAX_AGENT_ROUNDS):
        response = client.chat(
            messages=messages,
            system=system_prompt,
            tools=get_tool_definitions(),
            model=config.LLM_MODEL,
        )

        assistant_msg = client.build_assistant_message(response)
        messages.append(assistant_msg)
        memory.persist_message(session_id, "assistant", assistant_msg.get("content", ""))

        if response.stop_reason == "end_turn":
            if response.text:
                collected_text.append(response.text)
            reply_text = "\n\n".join(collected_text)

            hook_result = hooks.fire(
                "on_reply",
                HookContext(request_id=request_id, reply_text=reply_text),
            )
            if hook_result.override_output:
                reply_text = hook_result.override_output

            logger.log_conversation(request_id, chat_id, user_message, messages, reply_text)
            with _history_lock:
                history[chat_id] = messages
                _trim_history(chat_id)
            return reply_text

        elif response.stop_reason == "tool_use":
            thought = response.text or ""
            tool_use_results = []
            tool_names = []
            tool_inputs = []
            plan_submitted_this_round = False
            for tc in response.tool_calls:
                if tc.name == "submit_plan":
                    steps = tc.input.get("steps", [])
                    if steps:
                        plan_steps = steps
                        total_steps = len(plan_steps)
                        plan_submitted_this_round = True
                        if on_plan:
                            on_plan(plan_steps)
                    tool_use_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": "计划已发送给用户，等待用户确认后再执行。在用户回复确认之前不要执行任何工具。",
                        "is_error": False,
                    })
                    continue
                result = execute_tool(request_id, tc.name, tc.input, chat_id, sender_id)
                memory.track_tool_call(tc.name)
                tool_names.append(tc.name)
                tool_inputs.append(tc.input)

                if not result.success:
                    fail_counts[tc.name] = fail_counts.get(tc.name, 0) + 1
                    output = result.output
                    if fail_counts[tc.name] >= 2:
                        output += "\n[系统提示] 此工具已连续失败2次，请换一种方式完成任务或告知用户无法完成。"
                else:
                    fail_counts[tc.name] = 0
                    output = result.output

                tool_use_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": output,
                    "is_error": not result.success,
                })
            if tool_names:
                step_counter += 1
                # Notify user and LLM when exceeding planned steps
                if total_steps > 0 and step_counter > total_steps:
                    overshoot_hint = (
                        f"\n[系统提示] 当前已执行第{step_counter}步，超出原计划的{total_steps}步。"
                        "请告知用户需要额外步骤及原因，并继续完成任务。"
                    )
                    tool_use_results[-1]["content"] += overshoot_hint
                if on_progress:
                    on_progress(tool_names, tool_inputs, step_counter, total_steps, plan_steps, thought)

            # If plan was just submitted, pause and ask user to confirm
            if plan_submitted_this_round and not tool_names:
                built = client.build_tool_results(tool_use_results)
                if isinstance(built, list):
                    messages.extend(built)
                    for msg in built:
                        memory.persist_message(session_id, msg.get("role", "user"), msg.get("content", ""))
                else:
                    messages.append(built)
                    memory.persist_message(session_id, built.get("role", "user"), built.get("content", ""))

                confirm_text = "📋 以上是我的执行计划，确认后我将开始执行。\n（回复「执行」「好的」「确认」等继续，或告诉我需要调整的地方）"
                messages.append({"role": "assistant", "content": confirm_text})
                memory.persist_message(session_id, "assistant", confirm_text)

                with _history_lock:
                    history[chat_id] = messages
                    _trim_history(chat_id)
                return confirm_text

            built = client.build_tool_results(tool_use_results)
            if isinstance(built, list):
                messages.extend(built)
                for msg in built:
                    memory.persist_message(session_id, msg.get("role", "user"), msg.get("content", ""))
            else:
                messages.append(built)
                memory.persist_message(session_id, built.get("role", "user"), built.get("content", ""))

    return "处理轮数超限，请简化你的请求。"
