"""Analyst 专属工具: market_scanner, acquisition_research"""
from __future__ import annotations

from tools import ToolDef, register, _schema
from persona_tools._helpers import safe_call, llm_generate, save_to_doc


# ---------------------------------------------------------------------------
# market_scanner
# ---------------------------------------------------------------------------

_MARKET_SCANNER_SYSTEM = (
    "你是一位资深商业分析师，专注海外互联网市场。根据收集到的多维数据，"
    "生成市场机会扫描报告。严格按以下框架输出：\n\n"
    "## 市场概况\n赛道规模、增长率、发展阶段\n\n"
    "## PESTLE 宏观扫描\n"
    "| 维度 | 关键因素 | 趋势(INC↑/DEC↓/CONST→) | 对市场影响 |\n"
    "六行：Political(政策) / Economic(经济) / Social(社会) / "
    "Technological(技术) / Legal(法规) / Environmental(环境)\n\n"
    "## 信号扫描\n"
    "### 融资动态（市场验证信号）\n"
    "| 公司 | 轮次 | 金额 | 投资方 | 趋势 |\n\n"
    "### 新产品/新入场者\n"
    "| 产品 | 上线时间 | 定位 | 市场反应 | 趋势 |\n\n"
    "### 用户痛点（需求信号）\n"
    "| 痛点 | 来源 | 频次 | 趋势 |\n\n"
    "## 机会假设排序\n"
    "| # | 机会描述 | 信号强度 | 市场规模 | 进入难度 | 综合评分(★1-5) |\n"
    "列出 3-5 个，按综合评分降序，每个附切入建议。\n\n"
    "## Ansoff 增长矩阵\n"
    "分四象限分析增长路径：\n"
    "- 市场渗透（现有产品×现有市场）\n"
    "- 产品开发（新产品×现有市场）\n"
    "- 市场开发（现有产品×新市场）\n"
    "- 多元化（新产品×新市场）\n\n"
    "## 风险提示\n需要关注的市场风险\n\n"
    "数据来源要标注，每个信号标注趋势方向。使用中文输出。"
)


def market_scanner(inputs: dict, context: dict) -> str:
    rid = context["request_id"]
    cid, uid = context.get("chat_id", ""), context.get("user_id", "")
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

    pestle = safe_call(rid, "web_search", {
        "query": f"{market} regulation policy government impact {time_window}",
    })
    if pestle:
        parts.append(f"## 政策法规\n{pestle}")

    tech_trends = safe_call(rid, "web_search", {
        "query": f"{market} technology disruption innovation trend {time_window}",
    })
    if tech_trends:
        parts.append(f"## 技术趋势\n{tech_trends}")

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
        doc_result = save_to_doc(rid, f"市场扫描: {market}", result, cid, uid)
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
    "根据收集到的数据，生成结构化拓客策略报告。严格按以下框架输出：\n\n"
    "## ICP（理想客户画像）\n"
    "- 公司画像: 行业/规模/阶段/地区\n"
    "- 决策者: 职位/关注点/预算权限\n"
    "- 影响者: 技术评估者/终端用户\n"
    "- 购买触发点: 什么事件驱动购买决策\n"
    "- 反面画像: 不适合的客户特征\n\n"
    "## 竞品获客方式\n"
    "| 竞品 | 主要渠道 | 策略 | 效果 | 可借鉴点 |\n\n"
    "## 渠道评估矩阵\n"
    "| 渠道 | CAC 估算 | LTV 潜力 | 可扩展性 | 启动难度 | 综合评分 |\n"
    "按综合评分排序。\n\n"
    "## 单元经济参考\n"
    "- 行业 CAC 基准\n- 目标 LTV/CAC 比 (>3x)\n- Payback Period 目标\n\n"
    "## Bull's Eye 渠道筛选\n"
    "- 内圈（优先）: 1-2 个高确信渠道\n"
    "- 中圈（测试）: 2-3 个待验证渠道\n"
    "- 外圈（观察）: 远期可能渠道\n\n"
    "## 冷启动 First 100 Customers 方案\n"
    "按首月可达量 × 单位成本排序，每个渠道给出具体执行步骤。\n\n"
    "## 增长实验设计\n"
    "| 实验名 | 假设 | 核心指标 | 预期时长 | 预算 |\n"
    "2-3 个可快速验证的实验。\n\n"
    "建议务实可执行，附带时间线。使用中文输出。"
)


def acquisition_research(inputs: dict, context: dict) -> str:
    rid = context["request_id"]
    cid, uid = context.get("chat_id", ""), context.get("user_id", "")
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

    icp = safe_call(rid, "web_search", {
        "query": f"{query_base} ideal customer profile ICP decision maker buyer persona",
    })
    if icp:
        parts.append(f"## ICP 参考\n{icp}")

    economics = safe_call(rid, "web_search", {
        "query": f"{product or target} CAC LTV unit economics SaaS benchmark",
    })
    if economics:
        parts.append(f"## 单元经济基准\n{economics}")

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
        doc_result = save_to_doc(rid, f"拓客策略: {target}", result, cid, uid)
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
