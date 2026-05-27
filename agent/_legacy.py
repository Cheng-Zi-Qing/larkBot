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
from tools import AUDIT_TOOLS, execute_tool, get_tool_definitions

history: dict[str, list[dict]] = defaultdict(list)
_history_lock = threading.Lock()

# Per-chat confirmed plan steps — survives across agent loops
_confirmed_plans: dict[str, list[str]] = {}
_plans_lock = threading.Lock()


class _CancelledError(Exception):
    """Raised when a cancel_event is set mid-loop."""


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


def _should_reflect(step_counter: int, total_steps: int) -> bool:
    """Decide whether to inject a reflect prompt after this step."""
    interval = config.REFLECT_INTERVAL
    if interval <= 0:
        return False
    # Periodic reflect every N steps
    if step_counter > 0 and step_counter % interval == 0:
        return True
    # Reflect when all planned steps are done
    if config.REFLECT_AFTER_PLAN and total_steps > 0 and step_counter == total_steps:
        return True
    return False


def _build_reflect_prompt(step_counter: int, total_steps: int, plan_steps: list[str]) -> str:
    """Build a reflect checkpoint prompt to inject into tool results."""
    progress = f"已完成 {step_counter} 步"
    if total_steps > 0:
        progress += f"（计划共 {total_steps} 步）"
        remaining = [f"  {i+1}. {s}" for i, s in enumerate(plan_steps) if i >= step_counter]
        remaining_text = "\n".join(remaining[:3]) if remaining else "（全部完成）"
    else:
        remaining_text = "（无预设计划）"

    return (
        f"\n\n[反思检查点] {progress}\n"
        f"剩余步骤:\n{remaining_text}\n"
        "请评估：\n"
        "1. 已收集的信息是否足以回答用户问题？\n"
        "2. 下一步：继续执行 / 调整计划 / 开始汇总\n"
        "评估后继续行动。"
    )


def _build_recovery_prompt(
    failed_tool: str, step_counter: int, total_steps: int, plan_steps: list[str],
) -> str:
    """Build a recovery-replan prompt when a tool fails repeatedly."""
    completed = [f"  ✅ {i+1}. {s}" for i, s in enumerate(plan_steps) if i < step_counter]
    remaining = [f"  ⬚ {i+1}. {s}" for i, s in enumerate(plan_steps) if i >= step_counter]
    progress_text = "\n".join(completed + remaining) if plan_steps else "（无预设计划）"

    return (
        f"\n\n[Recovery] 工具 {failed_tool} 连续失败2次。"
        "请基于已有进度重新规划剩余步骤，不要重头再来。\n"
        f"当前进度:\n{progress_text}\n"
        "选项：\n"
        "1. 换一种工具/方式完成当前步骤目标\n"
        "2. 跳过此步骤，用已有信息继续后续步骤\n"
        "3. 信息已足够，直接开始汇总输出\n"
        "请选择并继续。"
    )


def _plan_has_write_steps(plan_steps: list[str]) -> bool:
    """Check if any plan step involves write/create/delete operations."""
    _WRITE_KEYWORDS = (
        "创建", "写入", "新建", "生成", "输出文档", "落文档", "发送", "回复",
        "编辑", "修改", "更新", "追加", "覆写", "删除", "移动",
        "create", "write", "send", "edit", "delete", "update", "append",
    )
    for step in plan_steps:
        step_lower = step.lower()
        if any(kw in step_lower for kw in _WRITE_KEYWORDS):
            return True
    return False


def _user_pre_confirmed(messages: list[dict]) -> bool:
    """Check if the user already confirmed high-risk execution in recent messages."""
    _CONFIRM_KEYWORDS = ("执行", "确认", "好的", "可以", "继续", "没问题", "ok", "yes", "go")
    for msg in reversed(messages[-4:]):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            text = content.strip().lower()
            if any(kw in text for kw in _CONFIRM_KEYWORDS):
                return True
    return False


def _describe_tool_action(tool_name: str, tool_input: dict, operation: str) -> str:
    """Build a human-readable description of a high-risk tool action."""
    op_labels = {"create": "创建", "update": "修改", "delete": "删除"}
    op_zh = op_labels.get(operation, operation)

    target = ""
    for key in ("title", "name", "subject", "doc", "app_token", "sheet", "url"):
        val = tool_input.get(key, "")
        if val:
            target = val[:50]
            break
    if not target:
        for key in ("content", "text", "body"):
            val = tool_input.get(key, "")
            if val:
                target = val[:30] + "..." if len(val) > 30 else val
                break

    try:
        from bot import TOOL_LABELS
        tool_label = TOOL_LABELS.get(tool_name, tool_name)
    except ImportError:
        tool_label = tool_name
    if target:
        return f"{op_zh} — {tool_label}（{target}）"
    return f"{op_zh} — {tool_label}"


def run(request_id: str, chat_id: str, user_message: str, sender_id: str = "",
        on_progress=None, on_plan=None, cancel_event=None) -> str:
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
                           messages, on_progress, on_plan, cancel_event)
    except _CancelledError:
        # Don't save half-finished history — new task starts clean
        return ""
    except Exception as e:
        if "bad" not in type(e).__name__.lower():
            raise
        logger.log_error(request_id, "agent", "BadRequest_retry", stderr=str(e))
        with _history_lock:
            history[chat_id] = []
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
    step_counter = 0
    total_steps = 0
    plan_steps: list[str] = []
    fail_counts: dict[str, int] = {}
    confirmed_tools: set[str] = set()

    # Restore confirmed plan from previous loop (e.g. after plan pause + user confirm)
    with _plans_lock:
        saved_plan = _confirmed_plans.pop(chat_id, None)
    if saved_plan:
        plan_steps = saved_plan
        total_steps = len(plan_steps)

    # Workflow matching: inject steps/template into system prompt if matched
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
            tool_outputs = []
            tool_successes = []
            plan_submitted_this_round = False
            hitl_pending = False
            hitl_description = ""

            # --- Force plan-first: block execution if no plan exists in this session ---
            non_plan_calls = [tc for tc in response.tool_calls if tc.name != "submit_plan"]
            has_plan_call = any(tc.name == "submit_plan" for tc in response.tool_calls)
            # Plan confirmed only if submit_plan was called in THIS agent loop
            plan_already_confirmed = bool(plan_steps)
            # Only allow skipping plan for single read-only tools (low risk)
            _READ_ONLY_TOOLS = ("read_doc", "read_sheet", "read_table", "read_markdown",
                                "get_agenda", "get_my_tasks", "search_docs", "search_messages",
                                "search_chats", "search_tasks", "list_mail", "read_mail",
                                "wiki_list_spaces", "wiki_get_node", "wiki_list_nodes",
                                "drive_inspect", "field_list", "table_list", "view_list",
                                "record_list", "record_get", "base_get", "get_chat_history",
                                "check_freebusy", "find_room", "search_user", "search_meetings",
                                "recall_memory", "find_sheet")
            all_read_only = all(tc.name in _READ_ONLY_TOOLS for tc in non_plan_calls)
            if (not plan_already_confirmed and not has_plan_call
                    and len(non_plan_calls) >= 1 and not all_read_only):
                for tc in response.tool_calls:
                    tool_use_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": (
                            "[系统拦截] 你必须先调用 submit_plan 提交执行计划，"
                            "等待用户确认后再执行。请勿直接调用工具。"
                        ),
                        "is_error": True,
                    })
                built = client.build_tool_results(tool_use_results)
                if isinstance(built, list):
                    messages.extend(built)
                else:
                    messages.append(built)
                continue
            # --- End force plan-first ---

            for tc in response.tool_calls:
                if tc.name == "submit_plan":
                    # If plan already confirmed (restored from previous loop), skip re-submission
                    if plan_already_confirmed:
                        tool_use_results.append({
                            "type": "tool_result",
                            "tool_use_id": tc.id,
                            "content": "计划已确认，请直接执行。",
                            "is_error": False,
                        })
                        continue
                    steps = tc.input.get("steps", [])
                    if steps:
                        plan_steps = steps
                        total_steps = len(plan_steps)
                        plan_submitted_this_round = True
                    tool_use_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": "计划已提交，正在判断是否需要用户确认。",
                        "is_error": False,
                    })
                    continue

                # --- Human-in-the-loop: pause before first high-risk tool ---
                if (tc.name in AUDIT_TOOLS
                        and tc.name not in confirmed_tools
                        and not _user_pre_confirmed(messages)):
                    # Return confirmation request, don't execute
                    op = AUDIT_TOOLS[tc.name]
                    desc = _describe_tool_action(tc.name, tc.input, op)
                    tool_use_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": (
                            f"[系统拦截-需要确认] 即将执行高危操作: {desc}\n"
                            "已暂停执行，等待用户确认。用户确认后请重新调用此工具。"
                        ),
                        "is_error": True,
                    })
                    hitl_pending = True
                    hitl_description = desc
                    continue
                # --- End human-in-the-loop ---

                result = execute_tool(request_id, tc.name, tc.input, chat_id, sender_id)
                memory.track_tool_call(tc.name)
                tool_names.append(tc.name)
                tool_inputs.append(tc.input)
                tool_outputs.append(result.output)
                tool_successes.append(result.success)
                # Mark tool as confirmed after successful execution
                if tc.name in AUDIT_TOOLS and result.success:
                    confirmed_tools.add(tc.name)

                if not result.success:
                    fail_counts[tc.name] = fail_counts.get(tc.name, 0) + 1
                    output = result.output
                    if fail_counts[tc.name] >= 2:
                        output += _build_recovery_prompt(
                            tc.name, step_counter, total_steps, plan_steps
                        )
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
                # Reflect checkpoint
                if _should_reflect(step_counter, total_steps):
                    tool_use_results[-1]["content"] += _build_reflect_prompt(
                        step_counter, total_steps, plan_steps
                    )
                # Convergence nudge at 80% of max rounds
                converge_at = int(config.MAX_AGENT_ROUNDS * 0.8)
                if round_idx == converge_at:
                    tool_use_results[-1]["content"] += (
                        f"\n[系统提示] 已使用 {round_idx + 1}/{config.MAX_AGENT_ROUNDS} 轮资源，"
                        "请基于已有信息开始汇总输出，避免继续搜索。"
                    )
                if on_progress and plan_steps:
                    on_progress(tool_names, tool_inputs, tool_outputs, tool_successes, step_counter, total_steps, plan_steps)

            # If plan was just submitted, show to user and decide whether to pause
            if plan_submitted_this_round:
                has_write_steps = _plan_has_write_steps(plan_steps)

                # Show plan to user (single notification point)
                if on_plan:
                    on_plan(plan_steps)

                # No write steps or user pre-confirmed → tell LLM to proceed
                if not has_write_steps or _user_pre_confirmed(messages):
                    # Rewrite tool result to instruct LLM to proceed directly
                    for tr in tool_use_results:
                        if tr.get("content") == "计划已提交，正在判断是否需要用户确认。":
                            tr["content"] = "计划已确认，请直接执行。"
                    built = client.build_tool_results(tool_use_results)
                    if isinstance(built, list):
                        messages.extend(built)
                        for msg in built:
                            memory.persist_message(session_id, msg.get("role", "user"), msg.get("content", ""))
                    else:
                        messages.append(built)
                        memory.persist_message(session_id, built.get("role", "user"), built.get("content", ""))
                    continue

                # Has write steps and no pre-confirm → pause for confirmation
                # Rewrite tool result to indicate waiting
                for tr in tool_use_results:
                    if tr.get("content") == "计划已提交，正在判断是否需要用户确认。":
                        tr["content"] = "计划已发送给用户，等待确认中。用户确认前不要执行任何工具。"

                built = client.build_tool_results(tool_use_results)
                if isinstance(built, list):
                    messages.extend(built)
                    for msg in built:
                        memory.persist_message(session_id, msg.get("role", "user"), msg.get("content", ""))
                else:
                    messages.append(built)
                    memory.persist_message(session_id, built.get("role", "user"), built.get("content", ""))

                confirm_text = "以上计划包含写入操作，确认后开始执行。\n（回复「执行」继续，或告诉我需要调整的地方）"
                messages.append({"role": "assistant", "content": confirm_text})
                memory.persist_message(session_id, "assistant", confirm_text)

                # Save plan so next loop can restore it after user confirms
                with _plans_lock:
                    _confirmed_plans[chat_id] = plan_steps

                with _history_lock:
                    history[chat_id] = messages
                    _trim_history(chat_id)
                return confirm_text

            # Human-in-the-loop: pause before high-risk tool execution
            if hitl_pending:
                built = client.build_tool_results(tool_use_results)
                if isinstance(built, list):
                    messages.extend(built)
                    for msg in built:
                        memory.persist_message(session_id, msg.get("role", "user"), msg.get("content", ""))
                else:
                    messages.append(built)
                    memory.persist_message(session_id, built.get("role", "user"), built.get("content", ""))

                confirm_text = (
                    f"⚠️ 即将执行: {hitl_description}\n"
                    "确认后我将继续执行。\n（回复「执行」「好的」「确认」等继续，或告诉我取消/调整）"
                )
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

    logger.log_error(request_id, "agent", "MaxRoundsExceeded",
                      stderr=f"Reached {config.MAX_AGENT_ROUNDS} rounds, step_counter={step_counter}")
    # Return any collected text instead of discarding it
    if collected_text:
        return "\n\n".join(collected_text) + "\n\n⚠️ 处理轮数已达上限，以上是已完成部分的结果。"
    return "处理轮数超限，请简化你的请求。"
