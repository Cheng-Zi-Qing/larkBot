"""PM 专属工具: competitive_landscape, generate_prd"""
from __future__ import annotations

from tools import ToolDef, register, _schema
from persona_tools._helpers import safe_call, llm_generate, save_to_doc, call_tool


# ---------------------------------------------------------------------------
# competitive_landscape
# ---------------------------------------------------------------------------

_COMPETITIVE_SYSTEM = (
    "你是一位资深 SaaS 产品分析师。根据收集到的网络数据和内部讨论，"
    "生成结构化竞品分析报告。格式要求：\n\n"
    "## 市场概览\n简述赛道现状、市场规模趋势\n\n"
    "## 竞品矩阵\n| 产品 | 定位 | 核心功能 | 定价模式 | 目标客户 | 差异化 |\n"
    "（每个竞品一行）\n\n"
    "## 竞争格局\n第一梯队/第二梯队分析\n\n"
    "## 用户痛点\n从评价和反馈中提炼的共性问题\n\n"
    "## 机会与威胁\n产品切入点建议\n\n"
    "数据来源要标注。如果某些数据缺失，标注'待补充'。使用中文输出。"
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
    "生成结构化 PRD（产品需求文档）。格式要求：\n\n"
    "## 背景与目标\n为什么做这个功能，解决什么问题\n\n"
    "## 用户故事\nAs a [角色], I want [功能], so that [价值]\n\n"
    "## 功能需求\n按优先级列出具体需求（P0/P1/P2）\n\n"
    "## 非功能需求\n性能、安全、兼容性等\n\n"
    "## 数据/指标\n核心指标和衡量方式\n\n"
    "## 验收标准\n具体的验收条件\n\n"
    "## 排期建议\n估算工作量和里程碑\n\n"
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
