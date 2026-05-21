"""全能管家专属工具: meeting_digest, weekly_report_builder"""
from __future__ import annotations

from tools import ToolDef, register, _schema
from persona_tools._helpers import safe_call, llm_generate, save_to_doc


# ---------------------------------------------------------------------------
# meeting_digest
# ---------------------------------------------------------------------------

_MEETING_DIGEST_SYSTEM = (
    "你是一位专业的会议纪要整理助手。根据提供的日历日程和聊天记录，"
    "为每场会议生成结构化纪要。格式要求：\n"
    "1. 每场会议标题、时间、参会人\n"
    "2. 讨论要点（分条列出）\n"
    "3. 决议（明确结论）\n"
    "4. Action Items（格式: - [ ] 事项 | 负责人 | 截止日期）\n"
    "最后汇总所有会议的 Action Items，按紧急程度排序。"
    "如果某些数据缺失，标注'数据未获取到'，基于已有数据尽力整理。"
    "使用中文输出。"
)


def meeting_digest(inputs: dict, context: dict) -> str:
    rid = context["request_id"]
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
        doc_result = save_to_doc(rid, title, result)
        result += f"\n\n---\n文档已保存: {doc_result}"

    return result


register(ToolDef(
    name="meeting_digest",
    description="整理会议纪要（决议+待办+负责人）",
    identity="",
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
    "生成结构化周报。格式要求：\n"
    "## 本周关键成果\n- 完成的重要事项\n\n"
    "## 进行中的工作\n- 当前进展和状态\n\n"
    "## 遇到的问题/风险\n- 需要关注或协助的事项\n\n"
    "## 下周计划\n- 重点任务和目标\n\n"
    "语言简洁专业，突出重点。如果某些数据缺失，基于已有数据尽力生成。"
    "使用中文输出。"
)


def weekly_report_builder(inputs: dict, context: dict) -> str:
    rid = context["request_id"]
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
        doc_result = save_to_doc(rid, title, result)
        result += f"\n\n---\n文档已保存: {doc_result}"

    return result


register(ToolDef(
    name="weekly_report_builder",
    description="自动汇总生成周报",
    identity="",
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
