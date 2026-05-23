"""submit_plan tool — lets the agent declare a multi-step execution plan."""
from __future__ import annotations

from tools import ToolDef, register, _schema

register(ToolDef(
    name="submit_plan",
    description=(
        "当你判断当前任务需要多步骤执行（如：搜索+读取+创建、调研+分析+输出等复杂链路）时，"
        "先调用此工具提交执行计划，让用户提前了解你接下来要做什么。"
        "简单问答或单步操作无需调用。"
    ),
    identity="",
    category="read",
    claude_schema=_schema("submit_plan", "Submit a multi-step execution plan before starting complex tasks", {
        "steps": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Ordered list of execution steps, each step should be a concise description including key targets (URL, filename, keyword, etc.)",
        },
    }, ["steps"]),
    python_func=lambda inp: "计划已提交，请开始执行。",
))
