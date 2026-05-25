"""市场全景分析 + 可行性评估 + 行业快扫 workflows."""
from __future__ import annotations

from workflows import WorkflowDef, register

register(WorkflowDef(
    id="market_analysis",
    name="市场全景分析",
    persona="analyst",
    trigger_patterns=[
        "市场分析", "市场全景", "分析市场", "市场规模",
        "tam", "sam", "som", "行业分析", "market analysis",
        "分析一下", "市场",
    ],
    steps=[
        "问题分解：将主题拆为子问题（规模/融资/玩家/技术/商业/政策/产业链）",
        "并行搜索：每个子问题独立 web_search/web_research",
        "交叉验证：关键数据至少 2 个独立来源",
        "TAM/SAM/SOM 双路径估算（Top-down + Bottom-up）",
        "Market Scan Chain：SWOT → PESTLE → Porter's → Ansoff",
        "结构化输出：按框架逐维度组织报告",
        "通过 create_doc 写入飞书文档",
    ],
    tools_hint=["web_research", "web_search", "web_read", "search_docs", "create_doc"],
    output_template=(
        "## 市场规模（TAM/SAM/SOM + 双路径交叉验证）\n"
        "## 行业阶段判断\n"
        "## PESTLE 扫描（表格：维度/现状/趋势/影响评级）\n"
        "## 技术可行性\n"
        "## 商业可行性（定价模型 + 单位经济）\n"
        "## 资本热度（融资表格）\n"
        "## 进入壁垒\n"
        "## 竞争格局（玩家矩阵）\n"
        "## 产业链地图\n"
        "## SWOT + Porter's + Ansoff\n"
        "## 结论与建议（Go/No-Go + 置信度）"
    ),
))

register(WorkflowDef(
    id="feasibility",
    name="可行性专项评估",
    persona="analyst",
    trigger_patterns=[
        "可行性", "可行性评估", "feasibility", "能不能做",
    ],
    steps=[
        "web_research 技术可行性（benchmark、延迟、成本）",
        "web_research 商业可行性（商业模式、单位经济）",
        "web_search 进入壁垒（竞争、合规、护城河）",
        "双路径估算目标市场规模",
        "深度搜索 → 输出可行性评估报告（含 Go/No-Go 建议 + 置信度评级）",
    ],
    tools_hint=["web_research", "web_search", "web_read", "search_docs"],
    output_template=(
        "## 技术可行性（Benchmark/延迟/成本/国产化适配）\n"
        "## 商业可行性（定价模型/付费意愿/单位经济）\n"
        "## 进入壁垒（合规/算力/数据飞轮/切换成本）\n"
        "## 目标市场规模（双路径）\n"
        "## Go/No-Go 建议 + 置信度评级"
    ),
))

register(WorkflowDef(
    id="quick_scan",
    name="行业快扫",
    persona="analyst",
    trigger_patterns=[
        "快扫", "快速扫描", "quick scan", "简单看看",
    ],
    steps=[
        "web_search 最新新闻和趋势",
        "web_search 市场趋势",
        "输出 1 页摘要：关键发现 / 值得深挖的方向 / 是否需要全景分析",
    ],
    tools_hint=["web_search", "web_read"],
    output_template=(
        "## 关键发现\n"
        "## 值得深挖的方向\n"
        "## 是否需要全景分析？（建议）"
    ),
))

register(WorkflowDef(
    id="funding_tracker",
    name="融资追踪",
    persona="analyst",
    trigger_patterns=[
        "融资追踪", "融资事件", "最近融资", "funding",
    ],
    steps=[
        "web_search AI 领域近期融资事件",
        "结构化输出：公司/轮次/金额/投资方/日期",
        "趋势点评",
    ],
    tools_hint=["web_search", "web_read"],
    output_template=(
        "## 融资事件\n| 公司 | 轮次 | 金额 | 投资方 | 日期 |\n"
        "## 趋势点评"
    ),
))
