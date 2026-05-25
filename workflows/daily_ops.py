"""日常运营 workflows — meeting digest, weekly report, daily briefing."""
from __future__ import annotations

from workflows import WorkflowDef, register

register(WorkflowDef(
    id="meeting_digest",
    name="会议纪要",
    persona="assistant",
    trigger_patterns=[
        "会议纪要", "整理会议", "会议记录", "meeting",
        "整理今天", "今天的会议",
    ],
    steps=[
        "获取日历日程（get_agenda）",
        "搜索会议记录（search_meetings）",
        "搜索相关聊天记录（search_messages）",
        "结构化整理：要点/决议/Action Items/未决项",
        "可选保存为飞书文档",
    ],
    tools_hint=["get_agenda", "search_meetings", "search_messages", "get_chat_history", "create_doc"],
    output_template=(
        "### [会议名称] | 时间 | 参会人\n"
        "#### 讨论要点\n"
        "#### 决议\n"
        "#### Action Items（事项/负责人/截止日/优先级）\n"
        "#### 未决项\n"
        "---\n"
        "## 全部 Action Items 汇总\n"
        "## 风险/阻塞项"
    ),
))

register(WorkflowDef(
    id="weekly_report",
    name="周报生成",
    persona="assistant",
    trigger_patterns=[
        "周报", "写周报", "生成周报", "weekly report",
    ],
    steps=[
        "获取本周日程（get_agenda）",
        "获取任务列表（get_my_tasks）",
        "搜索本周重要讨论（search_messages）",
        "搜索本周文档产出（search_docs）",
        "回忆本周对话（recall_memory）",
        "聚合生成：成果/进行中/风险/下周计划",
        "可选保存为飞书文档",
    ],
    tools_hint=["get_agenda", "get_my_tasks", "search_messages", "search_docs", "recall_memory", "create_doc"],
    output_template=(
        "## 📊 本周数据（完成任务/会议数/文档产出）\n"
        "## ✅ 关键成果\n"
        "## 🔄 进行中\n"
        "## ⚠️ 风险与阻塞\n"
        "## 📅 下周计划（优先级/事项/预计产出）"
    ),
))

register(WorkflowDef(
    id="daily_briefing",
    name="每日早报",
    persona="assistant",
    trigger_patterns=[
        "今天有什么", "今日安排", "早报", "daily briefing",
        "今天的安排",
    ],
    steps=[
        "获取今日日程（get_agenda）",
        "获取今日截止任务（get_my_tasks）",
        "回忆昨日遗留事项（recall_memory）",
        "生成结构化早报",
    ],
    tools_hint=["get_agenda", "get_my_tasks", "recall_memory"],
    output_template=(
        "## 📅 今日日程（时间/事件/状态）\n"
        "## ✅ 待办事项\n"
        "## 🎯 今日重点"
    ),
))

register(WorkflowDef(
    id="todo_sync",
    name="待办同步",
    persona="assistant",
    trigger_patterns=[
        "待办同步", "同步待办", "任务同步", "todo sync",
        "整理待办", "待办事项",
    ],
    steps=[
        "获取飞书任务列表（get_my_tasks）",
        "搜索聊天中提到的 action items（search_messages）",
        "回忆历史对话中的待办（recall_memory）",
        "合并去重 + 按优先级排序",
        "输出待办汇总 + 识别过期/遗漏项",
    ],
    tools_hint=["get_my_tasks", "search_messages", "search_tasks", "recall_memory"],
    output_template=(
        "## 📋 待办汇总（优先级/事项/来源/截止日/状态）\n"
        "## ⚠️ 过期/遗漏项\n"
        "## 💡 建议（合并/拆分/委派）"
    ),
))
