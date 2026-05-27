"""全能管家专属工具: meeting_digest, weekly_report_builder"""
from __future__ import annotations

from tools import ToolDef, register, _schema
from persona_tools._helpers import safe_call, llm_generate, save_to_doc


# ---------------------------------------------------------------------------
# meeting_digest
# ---------------------------------------------------------------------------

_MEETING_DIGEST_SYSTEM = (
    "你是一位专业的会议纪要整理助手。根据提供的日历日程和聊天记录，"
    "为每场会议生成结构化纪要。严格按以下格式输出：\n\n"
    "每场会议：\n"
    "### [会议名称] | 时间 | 参会人\n"
    "#### 讨论要点\n"
    "1. [议题] — [主导人] — [结论]\n\n"
    "#### 决议\n- ✅ [决议内容] (决策人: xxx)\n\n"
    "#### Action Items\n"
    "| 事项 | 负责人 | 截止日 | 优先级(P0/P1/P2) |\n\n"
    "#### 未决项\n- ❓ [待确认事项] (需要: xxx 确认/决策)\n\n"
    "---\n"
    "最后输出汇总章节：\n"
    "## 全部 Action Items 汇总（按紧急程度排序）\n"
    "## 风险/阻塞项\n"
    "## 建议下次会议议题\n\n"
    "数据缺失标注'数据未获取到'，基于已有数据尽力整理。使用中文输出。"
)


def meeting_digest(inputs: dict, context: dict) -> str:
    rid = context["request_id"]
    cid, uid = context.get("chat_id", ""), context.get("user_id", "")
    start = inputs.get("start", "")
    end = inputs.get("end", "")
    chat_id = inputs.get("chat_id", "")

    parts = []

    agenda = safe_call(rid, "get_agenda", {"start": start, "end": end} if start else {})
    if agenda:
        parts.append(f"## 日历日程\n{agenda}")

    meetings = safe_call(rid, "search_meetings", {"start": start, "end": end} if start and end else {"start": "", "end": ""})
    if meetings:
        parts.append(f"## 会议记录\n{meetings}")

    if chat_id:
        history = safe_call(rid, "get_chat_history", {"chat_id": chat_id, "page_size": 50})
        if history:
            parts.append(f"## 聊天记录\n{history}")

    msgs = safe_call(rid, "search_messages", {"query": "会议 讨论 决定"})
    if msgs:
        parts.append(f"## 相关消息\n{msgs}")

    if not parts:
        return "未获取到任何会议相关数据。请检查时间范围或稍后重试。"

    collected = "\n\n".join(parts)
    prompt = f"请根据以下数据整理会议纪要：\n\n{collected}"
    result = llm_generate(prompt, _MEETING_DIGEST_SYSTEM)

    if inputs.get("save") and result:
        title = f"会议纪要 {start or '今日'}"
        doc_result = save_to_doc(rid, title, result, cid, uid)
        result += f"\n\n---\n文档已保存: {doc_result}"

    return result


register(ToolDef(
    name="meeting_digest",
    description="整理会议纪要（决议+待办+负责人）",
    identity="",
    category="research",
    label="会议纪要",
    claude_schema=_schema(
        "meeting_digest",
        "Extract structured meeting minutes from calendar and chat data. "
        "Returns decisions, action items with owners and deadlines.",
        {
            "start": {"type": "string", "description": "Start datetime (ISO 8601), default today"},
            "end": {"type": "string", "description": "End datetime (ISO 8601), default today"},
            "chat_id": {"type": "string", "description": "Optional: specific chat to scan for discussion"},
            "save": {"type": "boolean", "description": "Save result as a Lark document (default false)"},
        },
    ),
    python_func=meeting_digest,
))


# ---------------------------------------------------------------------------
# weekly_report_builder
# ---------------------------------------------------------------------------

_WEEKLY_REPORT_SYSTEM = (
    "你是一位周报撰写助手。根据提供的日历、任务、消息等数据，"
    "生成结构化周报。严格按以下格式输出：\n\n"
    "## 📊 本周数据\n"
    "- 完成任务: X/Y (完成率 Z%)\n"
    "- 会议数: N 场\n"
    "- 文档产出: K 篇\n\n"
    "## ✅ 关键成果（vs 上周计划）\n"
    "| 计划项 | 状态(✅完成/🔄进行中/❌未启动) | 备注 |\n"
    "对比历史周报中的「下周计划」，逐项标注完成情况。\n\n"
    "## 🔄 进行中\n"
    "- [项目/事项]: 当前进展 + 下一步\n\n"
    "## ⚠️ 风险与阻塞\n"
    "| 风险 | 影响范围 | 需要的支持 |\n\n"
    "## 📅 下周计划\n"
    "| 优先级 | 事项 | 预计产出 |\n"
    "| P0 | ... | ... |\n\n"
    "## 🤝 跨团队协作\n"
    "- [与谁] [关于什么] [状态]\n\n"
    "语言简洁专业，突出重点。数据缺失时基于已有数据尽力生成。使用中文输出。"
)


def weekly_report_builder(inputs: dict, context: dict) -> str:
    rid = context["request_id"]
    cid, uid = context.get("chat_id", ""), context.get("user_id", "")
    period = inputs.get("period", "this_week")
    focus = inputs.get("focus", "")

    parts = []

    agenda = safe_call(rid, "get_agenda", {})
    if agenda:
        parts.append(f"## 本周日程\n{agenda}")

    tasks = safe_call(rid, "get_my_tasks", {})
    if tasks:
        parts.append(f"## 任务列表\n{tasks}")

    if focus:
        msgs = safe_call(rid, "search_messages", {"query": focus})
        if msgs:
            parts.append(f"## 相关讨论 ({focus})\n{msgs}")

    prev_report = safe_call(rid, "search_docs", {"query": "周报"})
    if prev_report:
        parts.append(f"## 历史周报参考\n{prev_report}")

    memory = safe_call(rid, "recall_memory", {"keyword": "周报", "time_range": "7d"})
    if memory:
        parts.append(f"## 本周对话回顾\n{memory}")

    if not parts:
        return "未获取到周报相关数据。请确保日历和任务系统中有数据。"

    collected = "\n\n".join(parts)
    prompt = f"报告周期: {period}\n\n请根据以下数据生成周报：\n\n{collected}"
    result = llm_generate(prompt, _WEEKLY_REPORT_SYSTEM)

    if inputs.get("save") and result:
        title = f"周报 ({period})"
        doc_result = save_to_doc(rid, title, result, cid, uid)
        result += f"\n\n---\n文档已保存: {doc_result}"

    return result


register(ToolDef(
    name="weekly_report_builder",
    description="自动汇总生成周报",
    identity="",
    category="research",
    label="周报生成",
    claude_schema=_schema(
        "weekly_report_builder",
        "Auto-generate a weekly report by collecting calendar, tasks, messages, and past reports. "
        "Produces a structured report with key achievements, in-progress work, blockers, and next-week plan.",
        {
            "period": {"type": "string", "description": "Report period: this_week, last_week, this_month (default this_week)"},
            "focus": {"type": "string", "description": "Optional focus areas to highlight"},
            "save": {"type": "boolean", "description": "Save result as a Lark document (default false)"},
        },
    ),
    python_func=weekly_report_builder,
))
