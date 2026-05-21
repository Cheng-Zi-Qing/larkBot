"""Analyst 专属工具: market_scanner, acquisition_research"""
from __future__ import annotations

from tools import ToolDef, register, _schema
from persona_tools._helpers import safe_call, llm_generate, save_to_doc


# ---------------------------------------------------------------------------
# market_scanner
# ---------------------------------------------------------------------------

_MARKET_SCANNER_SYSTEM = (
    "你是一位资深商业分析师，专注海外互联网市场。根据收集到的多维数据，"
    "生成市场机会扫描报告。格式要求：\n\n"
    "## 市场概况\n赛道规模、增长率、发展阶段\n\n"
    "## 信号扫描\n"
    "### 融资动态（市场验证信号）\n近期融资事件、金额、投资方\n\n"
    "### 新产品/新入场者\n新上线产品、产品迭代、市场反应\n\n"
    "### 用户痛点（需求信号）\n用户投诉、未满足需求、社区讨论热点\n\n"
    "## 机会假设\n基于以上信号，列出 3-5 个潜在机会，每个包含：\n"
    "- 机会描述\n- 支撑信号（引用具体数据）\n- 信号强度（强/中/弱）\n"
    "- 切入建议\n\n"
    "## 风险提示\n需要关注的市场风险\n\n"
    "数据来源要标注。使用中文输出。"
)


def market_scanner(inputs: dict, context: dict) -> str:
    rid = context["request_id"]
    market = inputs["market"]
    time_window = inputs.get("time_window", "month")
    lens = inputs.get("lens", "")

    parts = []

    overview = safe_call(rid, "web_research", {
        "topic": f"{market} market size growth trends {time_window} 2024 2025",
    })
    if overview:
        parts.append(f"## 市场概览\n{overview}")

    funding = safe_call(rid, "web_search", {
        "query": f"{market} startup funding round investment recent {time_window}",
    })
    if funding:
        parts.append(f"## 融资动态\n{funding}")

    launches = safe_call(rid, "web_search", {
        "query": f"{market} new product launch startup {time_window}",
    })
    if launches:
        parts.append(f"## 新产品上线\n{launches}")

    pain_points = safe_call(rid, "web_search", {
        "query": f"{market} user complaints pain points unmet needs reddit",
    })
    if pain_points:
        parts.append(f"## 用户痛点\n{pain_points}")

    if lens:
        lens_data = safe_call(rid, "web_search", {"query": f"{market} {lens}"})
        if lens_data:
            parts.append(f"## 专项视角 ({lens})\n{lens_data}")

    internal = safe_call(rid, "search_docs", {"query": market})
    if internal:
        parts.append(f"## 内部文档\n{internal}")

    memory = safe_call(rid, "recall_memory", {"keyword": market})
    if memory:
        parts.append(f"## 历史分析\n{memory}")

    if not parts:
        return f"未能获取到关于 {market} 的市场数据。请检查网络或换个关键词。"

    collected = "\n\n".join(parts)
    prompt = f"目标市场: {market}\n时间窗口: {time_window}\n专项视角: {lens or '综合'}\n\n{collected}"
    result = llm_generate(prompt, _MARKET_SCANNER_SYSTEM)

    if inputs.get("save") and result:
        doc_result = save_to_doc(rid, f"市场扫描: {market}", result)
        result += f"\n\n---\n文档已保存: {doc_result}"

    return result


register(ToolDef(
    name="market_scanner",
    description="市场机会扫描（融资+新品+痛点三角验证）",
    identity="",
    claude_schema=_schema(
        "market_scanner",
        "Scan a market for opportunities by triangulating funding signals, new product launches, "
        "and user pain points. Returns ranked opportunity hypotheses with supporting evidence.",
        {
            "market": {"type": "string", "description": "Market segment or category (e.g. 'Southeast Asia fintech')"},
            "time_window": {"type": "string", "description": "Time scope: week, month, quarter (default month)"},
            "lens": {"type": "string", "description": "Optional focus: funding, product_launches, regulatory, underserved"},
            "save": {"type": "boolean", "description": "Save result as a Lark document (default false)"},
        },
        ["market"],
    ),
    python_func=market_scanner,
))


# ---------------------------------------------------------------------------
# acquisition_research
# ---------------------------------------------------------------------------

_ACQUISITION_SYSTEM = (
    "你是一位增长和获客策略专家，熟悉北美、欧洲、东南亚市场。"
    "根据收集到的数据，生成结构化拓客策略报告。格式要求：\n\n"
    "## 目标客群画像\n谁是理想客户，他们在哪里聚集\n\n"
    "## 竞品获客方式\n竞争对手怎么获客的（渠道、策略、效果）\n\n"
    "## 渠道矩阵\n| 渠道 | 类型 | 预估 ROI | 启动难度 | 适合阶段 |\n"
    "按 ROI 排序\n\n"
    "## 具体打法\n每个推荐渠道的详细执行方案\n\n"
    "## 冷启动建议\n第一批 100 个客户怎么来\n\n"
    "## 增长实验设计\n2-3 个可快速验证的实验\n\n"
    "建议务实可执行，附带时间线。使用中文输出。"
)


def acquisition_research(inputs: dict, context: dict) -> str:
    rid = context["request_id"]
    target = inputs["target"]
    product = inputs.get("product", "")
    market = inputs.get("market", "")

    query_base = " ".join(filter(None, [target, product, market]))
    parts = []

    strategy = safe_call(rid, "web_research", {
        "topic": f"{query_base} customer acquisition strategy go-to-market",
    })
    if strategy:
        parts.append(f"## 获客策略研究\n{strategy}")

    channels = safe_call(rid, "web_search", {
        "query": f"{query_base} growth channels marketing strategy case study",
    })
    if channels:
        parts.append(f"## 增长渠道\n{channels}")

    competitors = safe_call(rid, "web_search", {
        "query": f"{query_base} competitor growth strategy how they acquire customers",
    })
    if competitors:
        parts.append(f"## 竞品获客方式\n{competitors}")

    community = safe_call(rid, "web_search", {
        "query": f"{target} community forum where to find {product or 'users'}",
    })
    if community:
        parts.append(f"## 目标客群聚集地\n{community}")

    internal = safe_call(rid, "search_docs", {"query": query_base})
    if internal:
        parts.append(f"## 内部文档\n{internal}")

    memory = safe_call(rid, "recall_memory", {"keyword": target})
    if memory:
        parts.append(f"## 历史讨论\n{memory}")

    if not parts:
        return f"未能获取到关于 {target} 的拓客数据。"

    collected = "\n\n".join(parts)
    prompt = (
        f"目标客群: {target}\n产品: {product or '未指定'}\n目标市场: {market or '未指定'}\n\n{collected}"
    )
    result = llm_generate(prompt, _ACQUISITION_SYSTEM)

    if inputs.get("save") and result:
        doc_result = save_to_doc(rid, f"拓客策略: {target}", result)
        result += f"\n\n---\n文档已保存: {doc_result}"

    return result


register(ToolDef(
    name="acquisition_research",
    description="拓客策略研究（渠道+打法+冷启动）",
    identity="",
    claude_schema=_schema(
        "acquisition_research",
        "Research customer acquisition strategies. Analyzes competitor growth tactics, "
        "maps channels by ROI, and designs cold-start playbooks.",
        {
            "target": {"type": "string", "description": "Target customer profile (e.g. 'B2B SaaS founders')"},
            "product": {"type": "string", "description": "Your product or service"},
            "market": {"type": "string", "description": "Target market region"},
            "save": {"type": "boolean", "description": "Save result as a Lark document (default false)"},
        },
        ["target"],
    ),
    python_func=acquisition_research,
))
