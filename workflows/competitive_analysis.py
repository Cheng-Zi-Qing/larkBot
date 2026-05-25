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

register(WorkflowDef(
    id="beachhead",
    name="Beachhead 市场选择",
    persona="pm",
    trigger_patterns=[
        "beachhead", "目标市场", "市场选择", "滩头市场",
        "市场优先级",
    ],
    steps=[
        "搜索候选细分市场信息",
        "5 维评分：规模 / 触达难度 / 紧迫度 / LTV / 竞争强度",
        "选总分最高且竞争≤3 的市场作为 Beachhead",
        "搜索 Beachhead 市场的 ICP 和决策者画像",
        "输出市场选择矩阵 + 推荐 Beachhead + 进入策略",
    ],
    tools_hint=["web_research", "web_search", "search_docs"],
    output_template=(
        "## 候选市场列表\n"
        "## 5 维评分矩阵（市场/规模/触达/紧迫度/LTV/竞争/总分）\n"
        "## 推荐 Beachhead 市场 + 理由\n"
        "## Beachhead ICP 画像\n"
        "## 进入策略与第一步行动"
    ),
))

register(WorkflowDef(
    id="pricing",
    name="定价策略分析",
    persona="pm",
    trigger_patterns=[
        "定价", "pricing", "价格策略", "定价对比",
        "价格分析", "定价模型",
    ],
    steps=[
        "搜索竞对定价页和套餐信息",
        "搜索行业定价模型（token/订阅/按效果/混合）",
        "搜索客户付费意愿和价格敏感度",
        "横评对比：竞对定价矩阵",
        "输出定价建议（模型 + 价格带 + 单位经济验证）",
    ],
    tools_hint=["web_research", "web_search", "web_read", "search_docs"],
    output_template=(
        "## 竞对定价矩阵（产品/模型/免费额度/付费起步/企业版）\n"
        "## 行业定价模型对比（按token/订阅/效果/混合）\n"
        "## 付费意愿分析\n"
        "## 单位经济验证（LTV/CAC/毛利率）\n"
        "## 定价建议（推荐模型 + 价格带 + 理由）"
    ),
))
