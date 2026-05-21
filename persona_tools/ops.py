"""Ops 专属工具: content_research_brief, campaign_tracker"""
from __future__ import annotations

from tools import ToolDef, register, _schema
from persona_tools._helpers import safe_call, llm_generate, save_to_doc, call_tool


# ---------------------------------------------------------------------------
# content_research_brief
# ---------------------------------------------------------------------------

_CONTENT_BRIEF_SYSTEM = (
    "你是一位资深内容运营专家，熟悉主流平台（微信、抖音、小红书、Twitter/X、LinkedIn）。"
    "根据收集到的数据，生成结构化内容策划 Brief。严格按以下框架输出：\n\n"
    "## 受众分析\n"
    "- 核心痛点 (Top 3，引用真实讨论数据)\n"
    "- 搜索意图分类: 信息型 / 导航型 / 交易型\n"
    "- 心理驱动: 最有效的心理学原理（社会认同/稀缺性/权威/互惠/锚定效应）\n\n"
    "## SEO 机会\n"
    "| 关键词/话题 | 搜索意图 | 竞争度(高/中/低) | 建议内容形式 |\n\n"
    "## 热门趋势\n"
    "| 趋势/话题 | 平台 | 互动量级 | 内容形式 | 可复用点 |\n\n"
    "## 竞品内容审计\n"
    "| 竞品 | 发布频率 | 主力平台 | 内容类型 | 互动量级 | 我方差异化机会 |\n\n"
    "## 平台适配方案\n"
    "| 平台 | 最佳格式 | 最佳长度 | 最佳发布时间 | 标签策略 |\n\n"
    "## 内容选题 (3-5 个)\n"
    "每个选题包含：\n"
    "- 标题\n"
    "- AIDA 框架: A(吸引点) → I(兴趣点) → D(欲望点) → A(行动点)\n"
    "- 心理学 Hook: 使用哪个心理学原理\n"
    "- 关键信息点\n"
    "- A/B 测试建议: A版(角度1) vs B版(角度2)\n\n"
    "## 品牌一致性\n基于内部品牌指南的注意事项\n\n"
    "建议具体可执行。使用中文输出。"
)


def content_research_brief(inputs: dict, context: dict) -> str:
    rid = context["request_id"]
    cid, uid = context.get("chat_id", ""), context.get("user_id", "")
    topic = inputs["topic"]
    platforms = inputs.get("platforms", "")
    content_type = inputs.get("content_type", "")

    query_base = " ".join(filter(None, [topic, platforms]))
    parts = []

    trending = safe_call(rid, "web_search", {
        "query": f"{query_base} trending content popular posts 2025",
    })
    if trending:
        parts.append(f"## 热门内容\n{trending}")

    audience = safe_call(rid, "web_search", {
        "query": f"{topic} audience pain points discussions questions",
    })
    if audience:
        parts.append(f"## 受众痛点\n{audience}")

    if platforms:
        platform_data = safe_call(rid, "web_search", {
            "query": f"{topic} {platforms} content strategy best practices",
        })
        if platform_data:
            parts.append(f"## 平台策略 ({platforms})\n{platform_data}")

    competitor_content = safe_call(rid, "web_search", {
        "query": f"{topic} competitor content marketing strategy examples",
    })
    if competitor_content:
        parts.append(f"## 竞品内容\n{competitor_content}")

    seo = safe_call(rid, "web_search", {
        "query": f"{topic} SEO keywords search volume content opportunities",
    })
    if seo:
        parts.append(f"## SEO 关键词\n{seo}")

    formats = safe_call(rid, "web_search", {
        "query": f"{topic} best content format engagement performance data",
    })
    if formats:
        parts.append(f"## 内容格式效果\n{formats}")

    brand = safe_call(rid, "search_docs", {"query": "品牌 指南 内容"})
    if brand:
        parts.append(f"## 内部品牌指南\n{brand}")

    direction = safe_call(rid, "search_messages", {"query": f"{topic} 内容 运营"})
    if direction:
        parts.append(f"## 团队讨论\n{direction}")

    if not parts:
        return f"未能获取到关于 {topic} 的内容数据。"

    collected = "\n\n".join(parts)
    prompt = (
        f"主题: {topic}\n目标平台: {platforms or '综合'}\n"
        f"内容类型: {content_type or '不限'}\n\n{collected}"
    )
    result = llm_generate(prompt, _CONTENT_BRIEF_SYSTEM)

    if inputs.get("save") and result:
        doc_result = save_to_doc(rid, f"内容策划: {topic}", result, cid, uid)
        result += f"\n\n---\n文档已保存: {doc_result}"

    return result


register(ToolDef(
    name="content_research_brief",
    description="生成内容策划 Brief（趋势+受众+竞品）",
    identity="",
    claude_schema=_schema(
        "content_research_brief",
        "Research and generate a content planning brief. Analyzes trending content, "
        "audience pain points, competitor strategies, and platform best practices.",
        {
            "topic": {"type": "string", "description": "Content topic or theme"},
            "platforms": {"type": "string", "description": "Target platforms: wechat, xiaohongshu, douyin, twitter, linkedin"},
            "content_type": {"type": "string", "description": "Content format: article, short_video, social_post"},
            "save": {"type": "boolean", "description": "Save result as a Lark document (default false)"},
        },
        ["topic"],
    ),
    python_func=content_research_brief,
))


# ---------------------------------------------------------------------------
# campaign_tracker
# ---------------------------------------------------------------------------

_CAMPAIGN_REPORT_SYSTEM = (
    "你是一位运营项目管理专家。根据活动跟踪表数据和最新进展，"
    "生成活动状态报告。严格按以下框架输出：\n\n"
    "## 整体进度\n完成率(X/Y 任务)、关键里程碑状态\n\n"
    "## AARRR 漏斗（如适用）\n"
    "| 阶段 | 目标 | 实际 | 达成率 | 趋势(↑→↓) |\n"
    "Acquisition / Activation / Retention / Revenue / Referral\n"
    "如果活动不涉及完整漏斗，只填写相关阶段。\n\n"
    "## 逾期项 🔴\n"
    "| 任务 | 负责人 | 原截止日 | 逾期天数 | 原因 |\n\n"
    "## 风险项 🟡\n"
    "| 任务 | 风险点 | 建议对策 |\n\n"
    "## 本周进展\n最新更新和变化\n\n"
    "## ROI 初估（活动结束后填写）\n"
    "- 投入: 人力 X 人天 + 预算 ¥Y\n"
    "- 产出: [核心指标] Z\n"
    "- 经验教训: 做对了什么/下次改进什么\n\n"
    "## 建议行动\n按优先级列出需立即处理的事项\n\n"
    "使用中文输出。"
)


def campaign_tracker(inputs: dict, context: dict) -> str:
    rid = context["request_id"]
    cid, uid = context.get("chat_id", ""), context.get("user_id", "")
    campaign = inputs["campaign"]
    action = inputs.get("action", "report")

    if action == "create":
        return _campaign_create(rid, campaign, inputs)
    return _campaign_report(rid, campaign, inputs)


def _campaign_create(rid: str, campaign: str, inputs: dict) -> str:
    parts = []

    plan_docs = safe_call(rid, "search_docs", {"query": campaign})
    if plan_docs:
        parts.append(f"## 活动文档\n{plan_docs}")

    msgs = safe_call(rid, "search_messages", {"query": campaign})
    if msgs:
        parts.append(f"## 相关讨论\n{msgs}")

    tasks = safe_call(rid, "search_tasks", {"query": campaign})
    if tasks:
        parts.append(f"## 已有任务\n{tasks}")

    collected = "\n\n".join(parts) if parts else "（无已有数据）"
    prompt = (
        f"活动名称: {campaign}\n\n"
        f"已有数据:\n{collected}\n\n"
        "请提取活动的所有任务项，整理为结构化列表，"
        "每项包含：任务名、负责人、截止日期、状态、优先级。"
        "输出为 markdown 表格。"
    )
    result = llm_generate(prompt, "你是一位运营项目管理专家。提取活动任务并结构化。使用中文输出。")

    base_token = inputs.get("base_token")
    table_id = inputs.get("table_id")
    if base_token and table_id:
        write_result = safe_call(rid, "write_table", {
            "base_token": base_token,
            "table_id": table_id,
            "records": result,
        })
        if write_result:
            result += f"\n\n---\n已写入多维表格: {write_result}"

    return result


def _campaign_report(rid: str, campaign: str, inputs: dict) -> str:
    parts = []

    base_token = inputs.get("base_token")
    table_id = inputs.get("table_id")
    if base_token and table_id:
        table_data = safe_call(rid, "read_table", {
            "base_token": base_token,
            "table_id": table_id,
        })
        if table_data:
            parts.append(f"## 跟踪表数据\n{table_data}")

    msgs = safe_call(rid, "search_messages", {"query": campaign})
    if msgs:
        parts.append(f"## 最新讨论\n{msgs}")

    tasks = safe_call(rid, "search_tasks", {"query": campaign})
    if tasks:
        parts.append(f"## 任务状态\n{tasks}")

    if not parts:
        return f"未找到活动 {campaign} 的跟踪数据。请提供 base_token 和 table_id，或先用 action=create 创建跟踪表。"

    collected = "\n\n".join(parts)
    prompt = f"活动名称: {campaign}\n\n{collected}"
    return llm_generate(prompt, _CAMPAIGN_REPORT_SYSTEM)


register(ToolDef(
    name="campaign_tracker",
    description="活动跟踪与状态报告",
    identity="",
    claude_schema=_schema(
        "campaign_tracker",
        "Track campaign progress. 'create' extracts tasks from docs/messages into a Bitable. "
        "'report' generates status report with overdue/at-risk items.",
        {
            "campaign": {"type": "string", "description": "Campaign name"},
            "action": {"type": "string", "description": "Action: create (build tracker) or report (status report). Default report."},
            "base_token": {"type": "string", "description": "Bitable app token (for reading/writing tracker)"},
            "table_id": {"type": "string", "description": "Bitable table ID (for reading/writing tracker)"},
        },
        ["campaign"],
    ),
    python_func=campaign_tracker,
))
