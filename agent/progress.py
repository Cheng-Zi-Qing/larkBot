from __future__ import annotations

import config
from agent.planner import PlanState


def notify_progress(
    plan_state: PlanState,
    tool_names: list[str],
    tool_inputs: list[dict],
    tool_outputs: list[str],
    tool_successes: list[bool],
    on_progress=None,
) -> None:
    """
    Trigger on_progress callback.
    Only fires when plan is confirmed AND tools actually executed.
    """
    if not on_progress:
        return
    if not plan_state.is_confirmed():
        return
    if not plan_state.steps:
        return
    if not tool_names:
        return

    on_progress(
        tool_names, tool_inputs, tool_outputs, tool_successes,
        plan_state.step_counter, plan_state.total_steps, plan_state.steps,
    )


def maybe_inject_reflect(
    tool_use_results: list[dict],
    step_counter: int,
    total_steps: int,
    plan_steps: list[str],
) -> None:
    """Inject reflect checkpoint into the last tool_result if conditions met."""
    if not tool_use_results:
        return
    if _should_reflect(step_counter, total_steps):
        tool_use_results[-1]["content"] += _build_reflect_prompt(
            step_counter, total_steps, plan_steps
        )


def maybe_inject_overshoot(
    tool_use_results: list[dict],
    step_counter: int,
    total_steps: int,
) -> None:
    """Notify when exceeding planned steps."""
    if not tool_use_results:
        return
    if total_steps > 0 and step_counter > total_steps:
        tool_use_results[-1]["content"] += (
            f"\n[系统提示] 当前已执行第{step_counter}步，超出原计划的{total_steps}步。"
            "请告知用户需要额外步骤及原因，并继续完成任务。"
        )


def maybe_inject_convergence(
    tool_use_results: list[dict],
    round_idx: int,
) -> None:
    """Convergence nudge at 80% of max rounds."""
    if not tool_use_results:
        return
    converge_at = int(config.MAX_AGENT_ROUNDS * 0.8)
    if round_idx == converge_at:
        tool_use_results[-1]["content"] += (
            f"\n[系统提示] 已使用 {round_idx + 1}/{config.MAX_AGENT_ROUNDS} 轮资源，"
            "请基于已有信息开始汇总输出，避免继续搜索。"
        )


def _should_reflect(step_counter: int, total_steps: int) -> bool:
    """Decide whether to inject a reflect prompt after this step."""
    interval = config.REFLECT_INTERVAL
    if interval <= 0:
        return False
    if step_counter > 0 and step_counter % interval == 0:
        return True
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
