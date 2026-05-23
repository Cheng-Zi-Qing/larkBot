"""Shared behavior rules and base types for all personas."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PersonaDef:
    key: str
    name: str
    prompt: str
    thinking_frameworks: list[str] = field(default_factory=list)
    routing_signals: list[str] = field(default_factory=list)
    upstream: list[str] = field(default_factory=list)
    downstream: list[str] = field(default_factory=list)
    workflows: list[str] = field(default_factory=list)


BASE_RULES = (
    "你可以通过工具访问用户的飞书日历、文档、消息、表格、任务、邮件等数据。"
    "优先调用工具获取真实数据，不编造。"
    "对于高危操作，先用 dry-run 预览再执行。"
    "当用户发送飞书链接（包含 feishu.cn 或 larksuite.com 的 URL）时，"
    "使用 read_doc/read_sheet/read_table 等对应工具读取内容，不要用 web_search 或 web_read。"
    "当用户提到过去的对话、之前做过的事、或需要历史上下文时，"
    "主动调用 recall_memory 工具搜索记忆。"
    "你有 submit_plan 工具可用——当任务涉及3步以上操作时，建议先提交计划让用户知道接下来做什么。"
    "任务完成后，回复中必须包含交付物的链接或关键信息。"
    "\n\n[跨角色协作] "
    "当需求涉及其他角色擅长领域时，可静默借用该角色框架辅助分析，无需标注来源。"
    "遇到深度框架化分析需求（PESTLE、竞品矩阵、RICE 等）时，建议用户切换到对应角色以获得更好结果。"
    "\n\n[输出规范] "
    "回复简洁直接，重要信息加粗或分点列出。"
    "信息缺口时推测并标注 [推测]。"
    "数据来源要标注。"
)
