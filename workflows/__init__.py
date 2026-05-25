"""Workflow registry — predefined step templates for complex tasks."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class WorkflowDef:
    id: str
    name: str
    persona: str
    trigger_patterns: list[str]
    steps: list[str]
    output_template: str = ""
    tools_hint: list[str] = field(default_factory=list)


_REGISTRY: dict[str, WorkflowDef] = {}


def register(wf: WorkflowDef):
    _REGISTRY[wf.id] = wf


def get(wf_id: str) -> Optional[WorkflowDef]:
    return _REGISTRY.get(wf_id)


def match(user_message: str, persona_key: str) -> Optional[WorkflowDef]:
    """Find the best matching workflow for a user message under current persona."""
    msg_lower = user_message.lower()
    for wf in _REGISTRY.values():
        if wf.persona != persona_key:
            continue
        for pattern in wf.trigger_patterns:
            if pattern in msg_lower:
                return wf
    return None


def build_workflow_context(wf: WorkflowDef, user_message: str) -> str:
    """Build workflow hint to inject into system prompt."""
    lines = [
        f"\n[工作流指引: {wf.name}]",
        "检测到此任务匹配预定义工作流，建议按以下步骤执行：",
    ]
    for i, step in enumerate(wf.steps, 1):
        lines.append(f"{i}. {step}")

    if wf.tools_hint:
        lines.append(f"\n建议工具: {', '.join(wf.tools_hint)}")

    if wf.output_template:
        lines.append(f"\n[输出格式]\n{wf.output_template}")

    lines.append("\n请调用 submit_plan 提交你的执行计划，然后逐步执行。")
    return "\n".join(lines)


# Import all workflow modules to trigger registration
from . import market_analysis, competitive_analysis, prd, content_plan, daily_ops, review
