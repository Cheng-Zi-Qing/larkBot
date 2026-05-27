"""PM 专属工具: competitive_landscape, generate_prd"""
from __future__ import annotations

from tools import ToolDef, register, _schema
from persona_tools._helpers import safe_call, llm_generate, save_to_doc, call_tool


# ---------------------------------------------------------------------------
# competitive_landscape
# ---------------------------------------------------------------------------

_COMPETITIVE_SYSTEM = (
    "你是一位资深 SaaS 产品分析师。根据收集到的网络数据和内部讨论，"
    "生成结构化竞品分析报告。严格按以下框架输出：\n\n"
    "## 市场规模 (TAM/SAM/SOM)\n"
    "- TAM（总可寻址市场）: 全球/全行业规模\n"
    "- SAM（可服务市场）: 目标区域+目标客群\n"
    "- SOM（可获取市场）: 短期可触达份额\n"
    "缺少精确数据时给出量级估算并标注依据。\n\n"
    "## Porter's Five Forces 分析\n"
    "| 力量 | 强度(高/中/低) | 关键因素 |\n"
    "五行：供应商议价力、买家议价力、替代品威胁、新进入者威胁、行业竞争强度。\n\n"
    "## 竞品 Battle Cards\n"
    "每家主要竞品一张卡片：\n"
    "- 核心卖点（一句话）\n- 定价模式与价格带\n- 主要弱点\n"
    "- 我方相对优势\n- 建议对策\n\n"
    "## 竞品矩阵\n| 产品 | 定位 | 核心功能 | 定价 | 目标客户 | 差异化 |\n\n"
    "## 定位矩阵\n选择 2 个最关键竞争维度作为 X/Y 轴，"
    "描述各竞品位置，标出空白区域（潜在机会）。\n\n"
    "## 用户痛点\n从评价和反馈中提炼共性问题，按频率排序。\n\n"
    "## 机会与威胁\n基于以上分析给出具体切入点建议，附优先级。\n\n"
    "数据来源要标注。缺失数据标注'待补充'。使用中文输出。"
)


def competitive_landscape(inputs: dict, context: dict) -> str:
    rid = context["request_id"]
    cid, uid = context.get("chat_id", ""), context.get("user_id", "")
    product = inputs["product"]
    focus = inputs.get("focus", "")

    parts = []

    research = safe_call(rid, "web_research", {"topic": f"{product} competitive analysis market landscape 2024 2025"})
    if research:
        parts.append(f"## 市场研究\n{research}")

    tam = safe_call(rid, "web_search", {"query": f"{product} market size TAM SAM SOM revenue forecast"})
    if tam:
        parts.append(f"## 市场规模数据\n{tam}")

    porters = safe_call(rid, "web_search", {"query": f"{product} industry analysis barriers entry supplier buyer power"})
    if porters:
        parts.append(f"## 行业结构\n{porters}")

    pricing = safe_call(rid, "web_search", {"query": f"{product} pricing plans comparison"})
    if pricing:
        parts.append(f"## 定价信息\n{pricing}")

    reviews = safe_call(rid, "web_search", {"query": f"{product} user reviews complaints alternatives"})
    if reviews:
        parts.append(f"## 用户评价\n{reviews}")

    if focus:
        focus_data = safe_call(rid, "web_search", {"query": f"{product} {focus}"})
        if focus_data:
            parts.append(f"## 专项分析 ({focus})\n{focus_data}")

    internal_docs = safe_call(rid, "search_docs", {"query": product})
    if internal_docs:
        parts.append(f"## 内部文档\n{internal_docs}")

    internal_msgs = safe_call(rid, "search_messages", {"query": product})
    if internal_msgs:
        parts.append(f"## 内部讨论\n{internal_msgs}")

    if not parts:
        return f"未能获取到关于 {product} 的任何数据。请检查网络连接或换个关键词。"

    collected = "\n\n".join(parts)
    prompt = f"目标产品/赛道: {product}\n专项关注: {focus or '无'}\n\n请生成竞品分析报告：\n\n{collected}"
    result = llm_generate(prompt, _COMPETITIVE_SYSTEM)

    if inputs.get("save") and result:
        doc_result = save_to_doc(rid, f"竞品分析: {product}", result, cid, uid)
        result += f"\n\n---\n文档已保存: {doc_result}"

    return result


register(ToolDef(
    name="competitive_landscape",
    description="结构化竞品分析",
    identity="",
    category="research",
    label="竞品分析",
    claude_schema=_schema(
        "competitive_landscape",
        "Research and generate a structured competitive analysis. "
        "Combines web research, pricing data, user reviews with internal Feishu docs and discussions.",
        {
            "product": {"type": "string", "description": "Product name or market category to analyze"},
            "focus": {"type": "string", "description": "Optional focus: pricing, PLG, enterprise, features"},
            "save": {"type": "boolean", "description": "Save result as a Lark document (default false)"},
        },
        ["product"],
    ),
    python_func=competitive_landscape,
))


# ---------------------------------------------------------------------------
# generate_prd
# ---------------------------------------------------------------------------

_PRD_SYSTEM = (
    "你是一位资深 SaaS 产品经理。根据需求描述和收集到的内部上下文，"
    "生成结构化 PRD（产品需求文档）。严格按以下框架输出：\n\n"
    "## 1. 问题定义\n"
    "- **谁 (Who)**: 受影响的用户群体\n"
    "- **什么 (What)**: 具体问题描述\n"
    "- **为什么 (Why)**: 为什么痛苦/重要\n"
    "- **证据 (Evidence)**: 支撑数据、用户反馈、内部讨论引用\n\n"
    "## 2. 目标用户与 JTBD\n"
    "主要 Persona + 次要 Persona，每个列出：\n"
    "| 用户角色 | 功能需求 (Functional) | 社会需求 (Social) | 情感需求 (Emotional) |\n\n"
    "## 3. 用户故事\n"
    "As a [角色], I want [功能], so that [价值]\n"
    "每个故事附验收标准：Given [前置条件] / When [操作] / Then [预期结果]\n\n"
    "## 4. 功能需求（RICE 优先级）\n"
    "| 需求 | Reach | Impact | Confidence | Effort | RICE Score |\n"
    "按 RICE 分数降序排列。Impact 用 3/2/1/0.5 打分。\n\n"
    "## 5. 非功能需求\n性能、安全、兼容性、可访问性\n\n"
    "## 6. 成功指标\n"
    "- 北极星指标 (North Star): 核心衡量指标\n"
    "- 护栏指标 (Guardrails): 不能恶化的指标\n\n"
    "## 7. 排期建议\n里程碑 + 依赖项 + 风险缓解措施\n\n"
    "引用内部已有的相关文档和讨论。使用中文输出。"
)


def generate_prd(inputs: dict, context: dict) -> str:
    rid = context["request_id"]
    cid, uid = context.get("chat_id", ""), context.get("user_id", "")
    feature = inputs["feature"]
    detail = inputs.get("detail", "")

    parts = []

    related_docs = safe_call(rid, "search_docs", {"query": feature})
    if related_docs:
        parts.append(f"## 相关内部文档\n{related_docs}")

    team_msgs = safe_call(rid, "search_messages", {"query": feature})
    if team_msgs:
        parts.append(f"## 团队讨论\n{team_msgs}")

    memory = safe_call(rid, "recall_memory", {"keyword": feature})
    if memory:
        parts.append(f"## 历史对话记忆\n{memory}")

    tasks = safe_call(rid, "search_tasks", {"query": feature})
    if tasks:
        parts.append(f"## 相关任务\n{tasks}")

    market = safe_call(rid, "web_search", {"query": f"{feature} SaaS product best practices"})
    if market:
        parts.append(f"## 市场参考\n{market}")

    collected = "\n\n".join(parts) if parts else "（无内部上下文数据）"
    prompt = (
        f"需求: {feature}\n"
        f"补充说明: {detail or '无'}\n\n"
        f"内部上下文:\n{collected}\n\n"
        "请生成 PRD。"
    )
    result = llm_generate(prompt, _PRD_SYSTEM)

    if inputs.get("save") and result:
        doc_result = save_to_doc(rid, f"PRD: {feature}", result, cid, uid)
        result += f"\n\n---\n文档已保存: {doc_result}"

    return result


register(ToolDef(
    name="generate_prd",
    description="生成产品需求文档（PRD）",
    identity="",
    category="research",
    label="生成 PRD",
    claude_schema=_schema(
        "generate_prd",
        "Generate a structured PRD by gathering internal docs, team discussions, memory, and market references. "
        "Optionally saves to a Lark document.",
        {
            "feature": {"type": "string", "description": "Feature name or requirement description"},
            "detail": {"type": "string", "description": "Additional context or requirements"},
            "save": {"type": "boolean", "description": "Save result as a Lark document (default false)"},
        },
        ["feature"],
    ),
    python_func=generate_prd,
))
