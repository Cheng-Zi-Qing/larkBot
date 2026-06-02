"""bot/formatter.py — 纯函数模块，格式化进度通知和工具输出摘要。"""
from __future__ import annotations

import json as _json
import re

from tools import get_tool_labels


# Backward-compatible module-level access (for `from bot import TOOL_LABELS`)
class _LazyLabels(dict):
    """Dict that populates on first access from TOOL_REGISTRY."""
    _loaded = False

    def _ensure(self):
        if not self._loaded:
            self.update(get_tool_labels())
            self._loaded = True

    def __getitem__(self, key):
        self._ensure()
        return super().__getitem__(key)

    def get(self, key, default=None):
        self._ensure()
        return super().get(key, default)

    def __contains__(self, key):
        self._ensure()
        return super().__contains__(key)

    def __iter__(self):
        self._ensure()
        return super().__iter__()

    def __len__(self):
        self._ensure()
        return super().__len__()

    def items(self):
        self._ensure()
        return super().items()

    def values(self):
        self._ensure()
        return super().values()

    def keys(self):
        self._ensure()
        return super().keys()


TOOL_LABELS: dict[str, str] = _LazyLabels()


def format_progress(
    tool_names: list[str], tool_inputs: list[dict],
    tool_outputs: list[str], tool_successes: list[bool],
    step: int, total: int, plan_steps: list[str] | None,
) -> str:
    """格式化进度通知文本。原 _make_progress_cb 内部逻辑提取为纯函数。"""
    lines: list[str] = []

    # Title: plan step description or tool labels as fallback
    step_desc = ""
    if plan_steps and step <= len(plan_steps):
        step_desc = plan_steps[step - 1]
    else:
        # No plan — use tool labels as description
        labels = [TOOL_LABELS.get(n, n) for n in tool_names]
        step_desc = "、".join(labels)
    prefix = f"[{step}/{total}]" if total > 0 else f"[第{step}步]"
    if total > 0 and step > total:
        prefix = f"[额外第{step - total}步]"
    lines.append(f"📎 {prefix} {step_desc}")

    # Each tool: label + input detail + output summary (max 50 chars each)
    all_success = True
    for name, inp, out, ok in zip(tool_names, tool_inputs, tool_outputs, tool_successes):
        label = TOOL_LABELS.get(name, name)
        detail = extract_detail(inp)
        lines.append(f"  调用 {label} {detail}".rstrip())
        summary = summarize_output(name, out, ok)
        if summary:
            lines.append(f"  → {summary}")
        if not ok:
            all_success = False

    # Status
    if all_success:
        lines.append("  ✅ 完成")
    else:
        lines.append("  ⚠️ 部分失败")

    return "\n".join(lines)


def format_plan(steps: list[str], auto_confirmed: bool = False) -> str:
    """格式化计划展示文本。"""
    if auto_confirmed:
        lines = ["📋 执行计划（已自动开始）:"]
    else:
        lines = ["📋 执行计划:"]
    for i, step in enumerate(steps, 1):
        lines.append(f"{i}. {step}")
    if auto_confirmed:
        lines.append("\n⏳ 正在自动处理中，每步进展会实时通知。")
    return "\n".join(lines)


def extract_detail(inp: dict) -> str:
    """Extract key info from tool input for display."""
    for key in ("doc", "url", "sheet", "app_token", "link"):
        val = inp.get(key, "")
        if val:
            # Truncate long URLs
            return val if len(val) <= 50 else val[:47] + "..."
    for key in ("query", "keyword", "content"):
        val = inp.get(key, "")
        if val:
            return f"「{val[:20]}」" if len(val) > 20 else f"「{val}」"
    for key in ("title", "name", "subject"):
        val = inp.get(key, "")
        if val:
            return val[:30]
    return ""


def extract_link(text: str) -> str:
    """从工具输出中提取飞书/lark链接"""
    match = re.search(r'https?://[^\s]*(?:feishu\.cn|larksuite\.com)[^\s\)\"]*', text)
    return match.group(0) if match else ""


def summarize_output(tool_name: str, output: str, success: bool) -> str:
    """从工具返回值中提取摘要，按工具类型智能提取"""
    if not output:
        return ""

    # 失败时直接提取错误原因
    if not success:
        text = output.split("[系统提示]")[0].strip()
        return f"❌ {text[:50]}" if len(text) > 50 else f"❌ {text}"

    text = output.split("[系统提示]")[0].strip()
    link = extract_link(text)

    # 搜索类：提取结果数量和标题
    _SEARCH_TOOLS = ("search_docs", "search_messages", "search_chats", "search_tasks",
                     "search_user", "search_meetings", "web_search", "find_sheet")
    if tool_name in _SEARCH_TOOLS:
        summary = _extract_search_summary(text)
        return summary

    # 创建类：提取标题 + 链接
    _CREATE_TOOLS = ("create_doc", "create_markdown", "create_sheet", "create_slides",
                     "create_event", "create_task", "base_create", "table_create",
                     "send_mail", "send_message", "wiki_create_node",
                     "drive_create_folder", "drive_upload")
    if tool_name in _CREATE_TOOLS:
        summary = text[:50] if len(text) > 50 else text
        if link:
            summary += f"\n  🔗 {link}"
        return summary

    # 编辑/写入类：简短确认 + 链接
    _WRITE_TOOLS = ("edit_doc", "overwrite_markdown", "patch_markdown", "append_sheet",
                    "write_table", "record_batch_create", "record_batch_update",
                    "record_upsert", "field_create", "update_event", "update_task",
                    "complete_task", "drive_move", "wiki_move")
    if tool_name in _WRITE_TOOLS:
        summary = text[:50] if len(text) > 50 else text
        if link:
            summary += f"\n  🔗 {link}"
        return summary

    # 读取类：提取有意义的摘要而非原始JSON
    _READ_TOOLS = ("read_doc", "read_sheet", "read_table", "read_markdown", "read_mail",
                   "get_agenda", "get_my_tasks", "get_chat_history", "record_list",
                   "record_get", "table_list", "field_list", "view_list",
                   "base_get", "drive_inspect", "wiki_get_node", "wiki_list_nodes",
                   "wiki_list_spaces", "list_mail", "check_freebusy")
    if tool_name in _READ_TOOLS:
        return _extract_read_summary(text)

    # 默认：截断
    summary = text[:50] + "..." if len(text) > 50 else text
    if link and link not in summary:
        summary += f"\n  🔗 {link}"
    return summary


def _extract_search_summary(text: str) -> str:
    """从搜索结果中提取数量和标题列表"""
    lines = text.split("\n")
    # 尝试提取数量
    count_match = re.search(r'(\d+)\s*(?:条|个|篇|项|results?)', text[:200])
    count = count_match.group(0) if count_match else ""
    # 提取标题行（常见格式: 1. xxx 或 - xxx 或 title: xxx）
    titles = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # 编号标题
        m = re.match(r'^\d+[\.\)]\s*(.+)', line)
        if m:
            titles.append(m.group(1)[:30])
        elif line.startswith("- "):
            titles.append(line[2:][:30])
        if len(titles) >= 3:
            break
    if count and titles:
        return f"找到 {count}: " + ", ".join(titles)
    if titles:
        return "找到: " + ", ".join(titles)
    if count:
        return f"找到 {count}"
    return text[:50] + "..." if len(text) > 50 else text


def _extract_read_summary(text: str) -> str:
    """从读取类工具的输出中提取有意义的摘要，跳过原始JSON"""
    # 如果是JSON，尝试提取关键字段
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            data = _json.loads(stripped)
            if isinstance(data, dict):
                # 常见结构: {"ok": true, "data": {...}} 或 {"ok": true, "identity": ..., "data": ...}
                inner = data.get("data", data)
                if isinstance(inner, dict):
                    title = inner.get("title", "") or inner.get("name", "") or inner.get("subject", "")
                    if title:
                        return f"已读取: {title[:40]}"
                    # 飞书文档结构：data.document.title
                    doc = inner.get("document", {})
                    if isinstance(doc, dict) and doc.get("title"):
                        return f"已读取: {doc['title'][:40]}"
                # 列表结构
                items = inner if isinstance(inner, list) else (inner.get("items", []) if isinstance(inner, dict) else [])
                if isinstance(items, list) and items:
                    return f"已读取 {len(items)} 条记录"
            elif isinstance(data, list):
                return f"已读取 {len(data)} 条记录"
            # 兜底：JSON 解析成功但没提取到有意义信息
            # 尝试估算内容大小
            content_len = len(stripped)
            if content_len > 500:
                return f"已读取文档（{content_len // 1000}KB）"
            return "已读取数据"
        except (_json.JSONDecodeError, TypeError):
            pass
    # 非JSON：取前50字
    return text[:50] + "..." if len(text) > 50 else text
