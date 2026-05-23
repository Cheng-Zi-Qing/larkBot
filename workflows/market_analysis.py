"""市场全景分析 workflow."""
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
        "保存为飞书文档（如用户要求）",
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
