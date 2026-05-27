"""bot/formatter.py — 纯函数模块，格式化进度通知和工具输出摘要。"""
from __future__ import annotations

import json as _json
import re

TOOL_LABELS: dict[str, str] = {
    "web_search": "搜索网络",
    "web_read": "读取网页",
    "web_research": "深度调研",
    "search_messages": "搜索消息",
    "get_chat_history": "读取聊天记录",
    "send_message": "发送消息",
    "reply_message": "回复消息",
    "search_chats": "搜索会话",
    "create_doc": "创建文档",
    "edit_doc": "编辑文档",
    "read_doc": "读取文档",
    "search_docs": "搜索文档",
    "read_table": "读取多维表格",
    "write_table": "写入多维表格",
    "query_table": "查询多维表格",
    "base_create": "创建多维表格",
    "base_get": "查看多维表格信息",
    "table_list": "列出数据表",
    "table_create": "创建数据表",
    "field_list": "列出字段",
    "field_create": "创建字段",
    "record_batch_create": "批量创建记录",
    "record_batch_update": "批量更新记录",
    "record_upsert": "更新插入记录",
    "record_delete": "删除记录",
    "record_get": "获取记录",
    "record_upload_attachment": "上传附件",
    "record_list": "列出记录",
    "view_list": "列出视图",
    "data_query": "数据查询",
    "read_sheet": "读取电子表格",
    "create_sheet": "创建电子表格",
    "append_sheet": "追加表格数据",
    "find_sheet": "查找表格数据",
    "get_agenda": "查看日程",
    "create_event": "创建日程",
    "update_event": "更新日程",
    "check_freebusy": "查询空闲时间",
    "find_room": "查找会议室",
    "get_my_tasks": "查看任务",
    "create_task": "创建任务",
    "update_task": "更新任务",
    "complete_task": "完成任务",
    "comment_task": "评论任务",
    "search_tasks": "搜索任务",
    "list_mail": "查看邮件",
    "read_mail": "读取邮件",
    "send_mail": "发送邮件",
    "reply_mail": "回复邮件",
    "search_user": "搜索用户",
    "search_meetings": "搜索会议",
    "drive_upload": "上传文件",
    "drive_download": "下载文件",
    "drive_export": "导出文档",
    "drive_import": "导入文档",
    "drive_create_folder": "创建文件夹",
    "drive_move": "移动文件",
    "drive_delete": "删除文件",
    "drive_comment": "文档评论",
    "drive_inspect": "查看文件信息",
    "wiki_list_spaces": "列出知识库",
    "wiki_create_node": "创建知识库节点",
    "wiki_get_node": "查看知识库节点",
    "wiki_list_nodes": "列出知识库节点",
    "wiki_move": "移动知识库节点",
    "create_markdown": "创建 Markdown",
    "read_markdown": "读取 Markdown",
    "overwrite_markdown": "覆写 Markdown",
    "patch_markdown": "修改 Markdown",
    "create_slides": "创建演示文稿",
    "doc_insert_media": "插入媒体",
    "competitive_landscape": "竞品分析",
    "generate_prd": "生成 PRD",
    "content_research_brief": "内容调研",
    "campaign_tracker": "活动追踪",
    "meeting_digest": "会议纪要",
    "weekly_report_builder": "周报生成",
    "market_scanner": "市场扫描",
    "acquisition_research": "获客研究",
    "recall_memory": "回忆记忆",
    "submit_plan": "制定计划",
}


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


def format_plan(steps: list[str]) -> str:
    """格式化计划展示文本。"""
    lines = ["📋 执行计划:"]
    for i, step in enumerate(steps, 1):
        lines.append(f"{i}. {step}")
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
