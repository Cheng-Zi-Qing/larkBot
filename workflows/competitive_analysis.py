"""竞品分析 workflow."""
from __future__ import annotations

from workflows import WorkflowDef, register

register(WorkflowDef(
    id="competitive_analysis",
    name="竞品深度分析",
    persona="pm",
    trigger_patterns=[
        "竞品分析", "竞品", "竞对", "competitive",
        "battlecard", "分析竞品",
    ],
    steps=[
        "问题分解：产品形态/定价/客户案例/vs同类差异/最近动态",
        "web_research 竞对官网产品页和定价页",
        "web_search 竞对客户案例和市场份额",
        "搜索内部已有竞品文档和团队讨论",
        "生成 Battlecard（定位/优势/短板/话术/定价/动态）",
        "功能矩阵对比 + 定位矩阵（X/Y轴标空白区域）",
        "输出差异化机会和建议行动",
    ],
    tools_hint=["web_research", "web_search", "web_read", "search_docs", "search_messages", "create_doc"],
    output_template=(
        "## 竞争格局总览（玩家/类型/产品形态/融资/优势）\n"
        "## Battlecard\n"
        "- 一句话定位\n- 核心优势 3 条\n- 核心短板 3 条\n"
        "- 我们赢的话术\n- 我们输的场景\n- 定价对比\n- 近期动态\n"
        "## 功能矩阵（表格）\n"
        "## 定位矩阵（关键竞争维度 X/Y）\n"
        "## 差异化机会\n"
        "## 建议行动"
    ),
))

register(WorkflowDef(
    id="battlecard",
    name="Battlecard 更新",
    persona="pm",
    trigger_patterns=[
        "battlecard", "更新battlecard", "更新 battlecard",
    ],
    steps=[
        "搜索竞对最近 3 月新闻和产品发布",
        "读取竞对官网 changelog",
        "读取已有 Battlecard 或历史分析",
        "增量更新各字段",
        "保存或更新文档",
    ],
    tools_hint=["web_search", "web_read", "search_docs", "create_doc"],
    output_template=(
        "## 一句话定位\n"
        "## 核心优势（3条）\n"
        "## 核心短板（3条）\n"
        "## 我们赢的话术\n"
        "## 我们输的场景\n"
        "## 定价对比\n"
        "## 近3月动态\n"
        "## 常见客户反对意见 & 应对"
    ),
))
