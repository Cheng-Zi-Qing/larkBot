from __future__ import annotations

import threading

import config
import hooks
import llm
import logger
import memory
import workflows
from hooks import HookContext
from tools import get_tool_definitions, AUDIT_TOOLS

from agent import history as hist
from agent.gate import RoundType, classify_round, build_plan_first_block_results
from agent.planner import PlanState, PlanDecision
from agent.executor import execute_round
from agent import progress as prog


class _CancelledError(Exception):
    """Raised when a cancel_event is set mid-loop."""


def run(request_id: str, chat_id: str, user_message: str, sender_id: str = "",
        on_progress=None, on_plan=None, cancel_event=None) -> str:
    hooks.fire("on_message_in", HookContext(request_id=request_id, chat_id=chat_id))

    rotated = memory.check_session_boundary()
    session_id = memory.get_current_session_id()

    messages = hist.load_or_restore(chat_id, session_id, rotated)

    hooks.fire("before_agent", HookContext(request_id=request_id, messages=messages))

    messages.append({"role": "user", "content": user_message})
    memory.persist_message(session_id, "user", user_message)

    try:
        return _agent_loop(request_id, chat_id, sender_id, session_id, user_message,
                           messages, on_progress, on_plan, cancel_event)
    except _CancelledError:
        return ""
    except Exception as e:
        if "bad" not in type(e).__name__.lower():
            raise
        logger.log_error(request_id, "agent", "BadRequest_retry", stderr=str(e))
        hist.clear(chat_id)
        messages = [{"role": "user", "content": user_message}]
        try:
            return _agent_loop(request_id, chat_id, sender_id, session_id, user_message,
                               messages, on_progress, on_plan, cancel_event)
        except _CancelledError:
            return ""
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
    cancel_event=None,
) -> str:
    client = llm.get_client()
    collected_text: list[str] = []
    fail_counts: dict[str, int] = {}
    confirmed_tools: set[str] = set()

    # Plan state
    plan_state = PlanState()
    plan_state.restore(chat_id)

    # Workflow matching
    workflow_context = ""
    wf = workflows.match(user_message, config.get_persona())
    if wf:
        workflow_context = workflows.build_workflow_context(wf, user_message)
    system_prompt = config.get_rich_system_prompt(workflow_context)

    for round_idx in range(config.MAX_AGENT_ROUNDS):
        if cancel_event and cancel_event.is_set():
            raise _CancelledError()

        response = client.chat(
            messages=messages,
            system=system_prompt,
            tools=get_tool_definitions(),
            model=config.LLM_MODEL,
        )

        assistant_msg = client.build_assistant_message(response)
        messages.append(assistant_msg)
        memory.persist_message(session_id, "assistant", assistant_msg.get("content", ""))

        # --- end_turn: return final text ---
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
            hist.save(chat_id, messages)
            return reply_text

        # --- tool_use: classify and dispatch ---
        elif response.stop_reason == "tool_use":
            disposition = classify_round(
                response.tool_calls, plan_state, confirmed_tools, messages
            )

            # === PLAN_FIRST_BLOCK ===
            if disposition == RoundType.PLAN_FIRST_BLOCK:
                tool_use_results = build_plan_first_block_results(response.tool_calls)
                _append_tool_results(client, messages, tool_use_results, session_id)
                continue

            # === PLAN_SUBMIT (submit_plan monopolizes the round) ===
            elif disposition == RoundType.PLAN_SUBMIT:
                pause_msg = _handle_plan_submit(
                    client, messages, response.tool_calls, plan_state,
                    session_id, chat_id, on_plan,
                )
                if pause_msg:
                    # Plan needs user confirmation — exit loop
                    hist.save(chat_id, messages)
                    return pause_msg
                # Plan auto-confirmed — continue to next round (LLM will execute)
                continue

            # === HITL_PAUSE ===
            elif disposition == RoundType.HITL_PAUSE:
                pause_msg = _handle_hitl_pause(
                    client, messages, response.tool_calls, plan_state,
                    confirmed_tools, fail_counts, session_id, chat_id, sender_id, request_id,
                )
                if pause_msg:
                    plan_state.persist(chat_id)
                    hist.save(chat_id, messages)
                    return pause_msg
                # If HITL was resolved (pre-confirmed tools executed), continue
                continue

            # === TOOL_EXEC (normal execution) ===
            else:
                exec_result = execute_round(
                    request_id, chat_id, sender_id,
                    response.tool_calls, confirmed_tools, messages,
                    fail_counts, plan_state.step_counter, plan_state.total_steps, plan_state.steps,
                )

                # Step counting
                if exec_result.tool_names:
                    plan_state.advance()

                    # Inject system hints
                    prog.maybe_inject_overshoot(
                        exec_result.tool_use_results, plan_state.step_counter, plan_state.total_steps
                    )
                    prog.maybe_inject_reflect(
                        exec_result.tool_use_results, plan_state.step_counter,
                        plan_state.total_steps, plan_state.steps,
                    )
                    prog.maybe_inject_convergence(exec_result.tool_use_results, round_idx)

                    # Notify user of progress
                    prog.notify_progress(
                        plan_state,
                        exec_result.tool_names, exec_result.tool_inputs,
                        exec_result.tool_outputs, exec_result.tool_successes,
                        on_progress,
                    )

                _append_tool_results(client, messages, exec_result.tool_use_results, session_id)

    # Max rounds exceeded
    logger.log_error(request_id, "agent", "MaxRoundsExceeded",
                     stderr=f"Reached {config.MAX_AGENT_ROUNDS} rounds, step_counter={plan_state.step_counter}")
    if collected_text:
        return "\n\n".join(collected_text) + "\n\n⚠️ 处理轮数已达上限，以上是已完成部分的结果。"
    return "处理轮数超限，请简化你的请求。"


# --- Internal handlers ---

def _handle_plan_submit(
    client, messages: list[dict], tool_calls: list,
    plan_state: PlanState, session_id: str, chat_id: str, on_plan,
) -> str | None:
    """
    Handle PLAN_SUBMIT round. Returns pause message if confirmation needed, None otherwise.
    Intercepts all non-submit_plan tools in the same round.
    """
    tool_use_results = []

    for tc in tool_calls:
        if tc.name == "submit_plan":
            steps = tc.input.get("steps", [])
            if steps:
                decision = plan_state.submit(steps, messages)
            else:
                decision = PlanDecision.AUTO_CONFIRM
            tool_use_results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": "计划已提交，正在判断是否需要用户确认。",
                "is_error": False,
            })
        else:
            # Intercept: submit_plan monopolizes this round
            tool_use_results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": "[系统拦截] 计划提交后需等待确认，本轮不执行其他工具。确认后将从第1步开始。",
                "is_error": True,
            })

    # Show plan to user
    if on_plan and plan_state.steps:
        on_plan(plan_state.steps, auto_confirmed=plan_state.is_confirmed())

    # Decision
    if plan_state.is_confirmed():
        # Auto-confirmed: rewrite tool_result and continue
        for tr in tool_use_results:
            if tr.get("content") == "计划已提交，正在判断是否需要用户确认。":
                tr["content"] = "计划已确认，请直接执行。"
        _append_tool_results(client, messages, tool_use_results, session_id)
        return None
    else:
        # Needs confirmation: rewrite and pause
        for tr in tool_use_results:
            if tr.get("content") == "计划已提交，正在判断是否需要用户确认。":
                tr["content"] = "计划已发送给用户，等待确认中。用户确认前不要执行任何工具。"
        _append_tool_results(client, messages, tool_use_results, session_id)

        confirm_text = "以上计划包含写入操作，确认后开始执行。\n（回复「执行」继续，或告诉我需要调整的地方）"
        messages.append({"role": "assistant", "content": confirm_text})
        memory.persist_message(session_id, "assistant", confirm_text)

        plan_state.persist_for_confirm(chat_id)
        return confirm_text


def _handle_hitl_pause(
    client, messages: list[dict], tool_calls: list,
    plan_state: PlanState, confirmed_tools: set[str],
    fail_counts: dict[str, int], session_id: str,
    chat_id: str, sender_id: str, request_id: str,
) -> str | None:
    """
    Handle HITL_PAUSE round.
    Execute safe tools, intercept audit tools needing confirmation.
    Gate is the sole HITL authority; executor is a pure executor.
    Returns pause message if confirmation needed, None if all resolved.
    """
    from agent.gate import describe_tool_action

    safe_calls = []
    hitl_calls = []
    for tc in tool_calls:
        if tc.name in AUDIT_TOOLS and tc.name not in confirmed_tools:
            hitl_calls.append(tc)
        else:
            safe_calls.append(tc)

    tool_use_results = []
    hitl_description = ""

    # Execute safe tools first
    if safe_calls:
        exec_result = execute_round(
            request_id, chat_id, sender_id,
            safe_calls, confirmed_tools, messages,
            fail_counts, plan_state.step_counter, plan_state.total_steps, plan_state.steps,
        )
        tool_use_results.extend(exec_result.tool_use_results)

    # Intercept audit tools
    for tc in hitl_calls:
        op = AUDIT_TOOLS[tc.name]
        desc = describe_tool_action(tc.name, tc.input, op)
        tool_use_results.append({
            "type": "tool_result",
            "tool_use_id": tc.id,
            "content": (
                f"[系统拦截-需要确认] 即将执行高危操作: {desc}\n"
                "已暂停执行，等待用户确认。用户确认后请重新调用此工具。"
            ),
            "is_error": True,
        })
        if not hitl_description:
            hitl_description = desc

    _append_tool_results(client, messages, tool_use_results, session_id)

    if hitl_description:
        confirm_text = (
            f"⚠️ 即将执行: {hitl_description}\n"
            "确认后我将继续执行。\n（回复「执行」「好的」「确认」等继续，或告诉我取消/调整）"
        )
        messages.append({"role": "assistant", "content": confirm_text})
        memory.persist_message(session_id, "assistant", confirm_text)
        return confirm_text

    return None


def _append_tool_results(client, messages: list[dict], tool_use_results: list[dict], session_id: str):
    """Build and append tool results to messages, persist to memory."""
    built = client.build_tool_results(tool_use_results)
    if isinstance(built, list):
        messages.extend(built)
        for msg in built:
            memory.persist_message(session_id, msg.get("role", "user"), msg.get("content", ""))
    else:
        messages.append(built)
        memory.persist_message(session_id, built.get("role", "user"), built.get("content", ""))
