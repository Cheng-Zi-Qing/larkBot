from __future__ import annotations

from enum import Enum

from agent.planner import PlanState, _user_pre_confirmed
from tools import AUDIT_TOOLS, TOOL_REGISTRY


class RoundType(Enum):
    PLAN_SUBMIT = "plan_submit"        # submit_plan monopolizes the round
    TOOL_EXEC = "tool_exec"            # normal tool execution
    HITL_PAUSE = "hitl_pause"          # high-risk tool pause
    PLAN_FIRST_BLOCK = "plan_first"    # no plan yet, block non-read-only tools


def _is_read_only(tool_name: str) -> bool:
    """Check if a tool is safe to execute without a plan (read-only, no external cost)."""
    td = TOOL_REGISTRY.get(tool_name)
    if td is None:
        # Unknown tools (e.g. submit_plan registered late) — safe to proceed
        return True
    return td.category == "read"


def classify_round(
    tool_calls: list,
    plan_state: PlanState,
    confirmed_tools: set[str],
    messages: list[dict],
) -> RoundType:
    """
    Classify a round of tool_calls into one disposition.

    Priority (high to low):
    1. PLAN_SUBMIT — submit_plan present and plan not yet confirmed
    2. PLAN_FIRST_BLOCK — no confirmed plan and non-read-only tools present,
       OR already executed 2+ tool rounds without a plan (even read-only)
    3. HITL_PAUSE — audit tool present and not pre-confirmed
    4. TOOL_EXEC — default
    """
    has_plan_call = any(tc.name == "submit_plan" for tc in tool_calls)
    plan_is_new = not plan_state.is_confirmed()

    # Priority 1: submit_plan monopolizes the round when plan is new
    if has_plan_call and plan_is_new:
        return RoundType.PLAN_SUBMIT

    # Priority 2: no plan yet and non-read-only tools → block
    non_plan_calls = [tc for tc in tool_calls if tc.name != "submit_plan"]
    all_read_only = all(_is_read_only(tc.name) for tc in non_plan_calls)
    if plan_is_new and not has_plan_call and non_plan_calls and not all_read_only:
        return RoundType.PLAN_FIRST_BLOCK

    # Priority 2b: already executed 2+ rounds without plan → block even read-only
    # This enforces "3步以上操作必须先提交计划" for all multi-step tasks
    if plan_is_new and not has_plan_call and non_plan_calls and plan_state.step_counter >= 2:
        return RoundType.PLAN_FIRST_BLOCK

    # Priority 3: audit tool present and not pre-confirmed
    has_unconfirmed_audit = any(
        tc.name in AUDIT_TOOLS and tc.name not in confirmed_tools
        for tc in tool_calls
    )
    if has_unconfirmed_audit and not _user_pre_confirmed(messages):
        return RoundType.HITL_PAUSE

    # Priority 4: normal execution
    return RoundType.TOOL_EXEC


def build_plan_first_block_results(tool_calls: list) -> list[dict]:
    """Build tool_result messages that block all tools when no plan exists."""
    results = []
    for tc in tool_calls:
        results.append({
            "type": "tool_result",
            "tool_use_id": tc.id,
            "content": (
                "[系统拦截] 你必须先调用 submit_plan 提交执行计划，"
                "等待用户确认后再执行。请勿直接调用工具。"
            ),
            "is_error": True,
        })
    return results


def describe_tool_action(tool_name: str, tool_input: dict, operation: str) -> str:
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
