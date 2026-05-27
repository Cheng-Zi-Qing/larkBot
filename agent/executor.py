from __future__ import annotations

from dataclasses import dataclass, field

import memory
from tools import AUDIT_TOOLS, execute_tool


@dataclass
class ExecResult:
    tool_names: list[str] = field(default_factory=list)
    tool_inputs: list[dict] = field(default_factory=list)
    tool_outputs: list[str] = field(default_factory=list)
    tool_successes: list[bool] = field(default_factory=list)
    tool_use_results: list[dict] = field(default_factory=list)


def execute_round(
    request_id: str,
    chat_id: str,
    sender_id: str,
    tool_calls: list,
    confirmed_tools: set[str],
    messages: list[dict],
    fail_counts: dict[str, int],
    step_counter: int,
    total_steps: int,
    plan_steps: list[str],
) -> ExecResult:
    """
    Execute a round of tool calls (pure executor, no HITL gating).
    HITL decisions are made by gate.py; this module only executes.
    Failed tools get recovery prompts after 2 consecutive failures.
    """
    result = ExecResult()

    for tc in tool_calls:
        # submit_plan in TOOL_EXEC round means plan already confirmed — no-op
        if tc.name == "submit_plan":
            result.tool_use_results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": "计划已确认，请直接执行。",
                "is_error": False,
            })
            continue

        # Normal execution
        tool_result = execute_tool(request_id, tc.name, tc.input, chat_id, sender_id)
        memory.track_tool_call(tc.name)
        result.tool_names.append(tc.name)
        result.tool_inputs.append(tc.input)
        result.tool_outputs.append(tool_result.output)
        result.tool_successes.append(tool_result.success)

        # Mark tool as confirmed after successful execution
        if tc.name in AUDIT_TOOLS and tool_result.success:
            confirmed_tools.add(tc.name)

        output = tool_result.output
        if not tool_result.success:
            fail_counts[tc.name] = fail_counts.get(tc.name, 0) + 1
            if fail_counts[tc.name] >= 2:
                output += _build_recovery_prompt(
                    tc.name, step_counter, total_steps, plan_steps
                )
        else:
            fail_counts[tc.name] = 0

        result.tool_use_results.append({
            "type": "tool_result",
            "tool_use_id": tc.id,
            "content": output,
            "is_error": not tool_result.success,
        })

    return result


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
