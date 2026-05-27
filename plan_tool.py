"""submit_plan tool — lets the agent declare a multi-step execution plan."""
from __future__ import annotations

from tools import ToolDef, register, _schema

register(ToolDef(
    name="submit_plan",
    description=(
        "当你判断当前任务需要多步骤执行（如：搜索+读取+创建、调研+分析+输出等复杂链路）时，"
        "先调用此工具提交执行计划，等待用户确认后再开始执行。"
        "提交计划后不要立即调用其他工具，必须等用户回复确认。"
        "简单问答或单步操作无需调用。"
        "\n\n计划要求："
        "\n- 每步写清目标和预期产出（如「搜索3-5个来源获取X数据」「汇总对比后输出表格」）"
        "\n- 最后一步必须是汇总/输出（确保有收敛终点）"
        "\n- 你决定步骤数和每步搜索量，用户只审核合理性"
    ),
    identity="",
    category="read",
    label="制定计划",
    claude_schema=_schema("submit_plan", "Submit a multi-step execution plan before starting complex tasks", {
        "steps": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Ordered list of execution steps. Each step should describe: goal, key targets (URL/keyword/etc), and expected output.",
        },
    }, ["steps"]),
    python_func=lambda inp: "计划已提交，请开始执行。",
))
