from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import agent
import config
import hooks
import logger
import web_tools  # noqa: F401 — registers web tools
import memory  # noqa: F401 — registers recall_memory tool
import persona_tools  # noqa: F401 — registers persona tools
import plan_tool  # noqa: F401 — registers submit_plan tool
from hooks import HookContext

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


def start_event_consumer() -> subprocess.Popen:
    proc = subprocess.Popen(
        [
            "lark-cli", "event", "consume", "im.message.receive_v1",
            "--as", "bot",
            "--jq", 'select(.chat_type=="p2p" and .message_type=="text")',
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    ready = False

    def read_stderr():
        nonlocal ready
        for line in proc.stderr:
            line = line.rstrip()
            if "[event] ready" in line:
                ready = True
                print("[BOT] Event consumer ready", file=sys.stderr)
            elif "[event] exited" in line:
                print(f"[BOT] Event consumer exited: {line}", file=sys.stderr)
            elif line:
                print(f"[BOT][stderr] {line}", file=sys.stderr)

    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stderr_thread.start()

    for _ in range(300):
        if ready:
            break
        time.sleep(0.1)
    if not ready:
        raise RuntimeError("Event consumer failed to become ready within 30s")

    return proc


def send_reply(chat_id: str, text: str, reply_to: str | None = None):
    if reply_to:
        cmd = [
            "lark-cli", "im", "+messages-reply",
            "--as", "bot", "--message-id", reply_to, "--text", text,
        ]
    else:
        cmd = [
            "lark-cli", "im", "+messages-send",
            "--as", "bot", "--chat-id", chat_id, "--text", text,
        ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            print(f"[BOT] send_reply failed (rc={result.returncode}): {result.stderr[:200]}", file=sys.stderr)
    except subprocess.TimeoutExpired:
        print(f"[BOT] Reply timed out for chat {chat_id}", file=sys.stderr)
    except Exception as e:
        print(f"[BOT] send_reply error: {e}", file=sys.stderr)


def handle_command(content: str, chat_id: str, request_id: str):
    cmd = content.strip().lower()
    # /assis* aliases: map to persona key and optionally forward remaining text as message
    _ASSIS_MAP = {
        "/assis-a": "analyst",
        "/assis-p": "pm",
        "/assis-o": "ops",
        "/assis-r": "reviewer",
        "/assis": "assistant",
    }
    for prefix, persona_key in _ASSIS_MAP.items():
        if cmd == prefix or cmd.startswith(prefix + " "):
            name = config.set_persona(persona_key)
            remainder = content.strip()[len(prefix):].strip()
            if remainder:
                send_reply(chat_id, f"已切换为: {name}")
                # Forward remaining text as a user message
                handle_message({"chat_id": chat_id, "sender_id": "", "content": remainder, "message_id": ""})
            else:
                send_reply(chat_id, f"已切换为: {name}")
            return
    if cmd == "/reload-hooks":
        hooks.reload_custom_hooks()
        send_reply(chat_id, "Hooks reloaded.")
    elif cmd == "/stats":
        persona = config.get_persona()
        name = config.PERSONAS[persona]["name"]
        send_reply(chat_id, f"Bot is running. Persona: {name}. Request: {request_id}")
    elif cmd == "/ping":
        send_reply(chat_id, "pong")
    elif cmd == "/role":
        lines = ["当前角色：" + config.PERSONAS[config.get_persona()]["name"], ""]
        for key, name in config.list_personas().items():
            lines.append(f"  /{key} — {name}")
        lines.append("")
        lines.append("别名：/assis /assis-a /assis-p /assis-o")
        send_reply(chat_id, "\n".join(lines))
    elif cmd.lstrip("/") in config.PERSONAS:
        key = cmd.lstrip("/")
        name = config.set_persona(key)
        send_reply(chat_id, f"已切换为: {name}")
    else:
        send_reply(chat_id, f"未知命令: {content}\n发送 /role 查看角色列表")


_seen_messages: dict[str, float] = {}
_seen_lock = threading.Lock()

_DEDUP_WINDOW = 60.0  # seconds


def _dedup_check(message_id: str) -> bool:
    """Return True if this message_id was already seen (duplicate)."""
    if not message_id:
        return False
    now = time.time()
    with _seen_lock:
        if len(_seen_messages) > 500:
            _seen_messages.clear()
        if message_id in _seen_messages:
            return True
        _seen_messages[message_id] = now
    return False


# --- Task Queue: per-chat cancel + intent classification ---

@dataclass
class _ChatTask:
    """Tracks a running agent task for a chat."""
    cancel_event: threading.Event
    original_message: str
    request_id: str


_active_tasks: dict[str, _ChatTask] = {}  # chat_id → running task
_tasks_lock = threading.Lock()

_INTENT_PROMPT = (
    "你是一个意图分类器。用户之前发了一条消息启动了任务，现在又发了新消息。\n"
    "请判断新消息的意图，只输出一个词：\n"
    "- cancel — 用户想取消/撤回/重来/换个问法\n"
    "- supplement — 用户在补充信息/纠正细节/追加要求（原始任务目标不变）\n"
    "- confirm — 用户在确认执行（如：好的、执行、确认、可以）\n"
    "- status — 用户在打招呼/问在不在/闲聊/不需要任何操作（如：你在么、你是谁、在吗）\n"
    "- new_task — 用户发了一个全新的、与旧任务无关的指令\n\n"
    "旧任务: {old_message}\n"
    "新消息: {new_message}\n\n"
    "只输出 cancel/supplement/confirm/status/new_task 中的一个词。"
)


def _classify_intent(old_message: str, new_message: str) -> str:
    """LLM call to classify new message intent relative to running task."""
    try:
        import llm
        client = llm.get_client()
        prompt = _INTENT_PROMPT.format(old_message=old_message[:200], new_message=new_message[:200])
        resp = client.chat(
            messages=[{"role": "user", "content": prompt}],
            system="只输出一个分类词，不要输出其他内容。",
            tools=[],
            model=config.LLM_MODEL,
            max_tokens=10,
        )
        result = (resp.text or "").strip().lower()
        if result in ("cancel", "supplement", "confirm", "status", "new_task"):
            return result
        # Fuzzy match
        for word in ("cancel", "supplement", "confirm", "status", "new_task"):
            if word in result:
                return word
        return "new_task"
    except Exception:
        return "new_task"


def handle_message(event: dict):
    chat_id = event.get("chat_id", "")
    sender_id = event.get("sender_id", "")
    content = event.get("content", "")
    message_id = event.get("message_id", "")
    event_id = event.get("event_id", "")
    request_id = f"req_{uuid.uuid4().hex[:12]}"

    if not content:
        return

    # Deduplicate: use event_id first, fallback to message_id
    dedup_key = event_id or message_id
    if _dedup_check(dedup_key):
        print(f"[BOT] [{request_id}] Dedup skip: {dedup_key}", file=sys.stderr)
        return

    # Check if there's a running task for this chat
    with _tasks_lock:
        active = _active_tasks.get(chat_id)

    if active and not active.cancel_event.is_set():
        # There's a running task — classify intent
        intent = _classify_intent(active.original_message, content)
        print(f"[BOT] [{request_id}] Intent: {intent} (old: {active.original_message[:40]})", file=sys.stderr)

        if intent == "confirm":
            # Confirmation — keep history, agent loop picks up confirm message
            _run_task(request_id, chat_id, sender_id, content, message_id, clear_history=False)
            return

        elif intent == "status":
            # Status check / greeting — respond without cancelling the running task
            send_reply(chat_id, f"🔄 正在执行中: {active.original_message[:50]}\n请稍候，完成后会通知你。")
            return

        elif intent == "cancel":
            # Cancel old task and start fresh with new message (if any real content)
            active.cancel_event.set()
            send_reply(chat_id, f"⏹️ 已取消: {active.original_message[:50]}")
            # Don't start new task for pure cancel messages
            return

        elif intent == "supplement":
            # Cancel old, merge messages, restart
            active.cancel_event.set()
            merged = f"{active.original_message}\n\n[补充] {content}"
            send_reply(chat_id, f"📝 收到补充，重新执行:\n原始: {active.original_message[:50]}\n补充: {content[:50]}")
            _run_task(request_id, chat_id, sender_id, merged, message_id)
            return

        elif intent == "new_task":
            # Cancel old, start new
            active.cancel_event.set()
            send_reply(chat_id, f"⏹️ 已取消旧任务: {active.original_message[:50]}\n▶️ 开始新任务")
            _run_task(request_id, chat_id, sender_id, content, message_id)
            return

    # No active task — check if resuming after plan confirmation
    has_pending_plan = bool(agent.history.get(chat_id))
    _run_task(request_id, chat_id, sender_id, content, message_id, clear_history=not has_pending_plan)


def _run_task(request_id: str, chat_id: str, sender_id: str, content: str, message_id: str,
              clear_history: bool = True):
    """Start a new agent task in the thread pool."""
    cancel_event = threading.Event()
    task = _ChatTask(cancel_event=cancel_event, original_message=content, request_id=request_id)

    with _tasks_lock:
        old = _active_tasks.get(chat_id)
        if old:
            old.cancel_event.set()
        _active_tasks[chat_id] = task

    # Only clear history when starting a genuinely new task
    if clear_history:
        agent.history.pop(chat_id, None)
        with agent._plans_lock:
            agent._confirmed_plans.pop(chat_id, None)

    def _execute():
        try:
            _process_message(request_id, chat_id, sender_id, content, message_id, cancel_event)
        finally:
            with _tasks_lock:
                # Only clear if this is still the active task
                if _active_tasks.get(chat_id) is task:
                    del _active_tasks[chat_id]

    _executor.submit(_execute)


def _process_message(
    request_id: str, chat_id: str, sender_id: str, content: str, message_id: str,
    cancel_event: threading.Event | None = None,
):
    print(f"[BOT] [{request_id}] From {sender_id}: {content[:80]}", file=sys.stderr)

    if content.startswith("/"):
        handle_command(content, chat_id, request_id)
        return

    try:
        reply = agent.run(request_id, chat_id, content, sender_id=sender_id,
                          on_progress=_make_progress_cb(chat_id),
                          on_plan=_make_plan_cb(chat_id),
                          cancel_event=cancel_event)

        # If cancelled mid-run, don't send reply — new task owns the chat now
        if cancel_event and cancel_event.is_set():
            print(f"[BOT] [{request_id}] Cancelled, discarding result", file=sys.stderr)
            return

        if not reply or not reply.strip():
            reply = "（模型返回为空，请重新描述你的问题）"

        # Routing suggestion: hint user if another persona is better suited
        suggested = config.detect_persona_routing(content)
        if suggested:
            persona_name = config.PERSONAS.get(suggested, {}).get("name", suggested)
            reply += f"\n\n💡 这类问题切换到 /{suggested}（{persona_name}）可能效果更好"

        send_reply(chat_id, reply)
    except Exception as e:
        # If cancelled, swallow errors silently
        if cancel_event and cancel_event.is_set():
            print(f"[BOT] [{request_id}] Cancelled (exception swallowed): {e}", file=sys.stderr)
            return
        logger.log_error(request_id, "bot", "AgentError", stderr=str(e))
        err_name = type(e).__name__
        err_detail = str(e)[:200]
        if "rate" in err_name.lower():
            send_reply(chat_id, "当前请求太频繁，请稍等片刻再试。")
        elif "timeout" in err_name.lower():
            send_reply(chat_id, "请求超时了，请稍后再试。")
        elif "content-blocked" in err_detail or "content_blocked" in err_detail:
            send_reply(chat_id, "请求被上游服务拦截，请稍后重试。如持续出现请联系管理员。")
        else:
            send_reply(chat_id, f"处理失败（{err_name}）：{err_detail}")


_executor = ThreadPoolExecutor(max_workers=4)


def _make_progress_cb(chat_id: str):
    last_ts = 0.0

    def _on_progress(tool_names: list[str], tool_inputs: list[dict],
                     tool_outputs: list[str], tool_successes: list[bool],
                     step: int, total: int, plan_steps: list[str] | None):
        nonlocal last_ts
        now = time.time()
        if now - last_ts < 1.0:
            return
        last_ts = now

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
            detail = _extract_detail(inp)
            lines.append(f"  调用 {label} {detail}".rstrip())
            summary = _summarize_output(name, out, ok)
            if summary:
                lines.append(f"  → {summary}")
            if not ok:
                all_success = False

        # Status
        if all_success:
            lines.append("  ✅ 完成")
        else:
            lines.append("  ⚠️ 部分失败")

        send_reply(chat_id, "\n".join(lines))

    return _on_progress


def _extract_detail(inp: dict) -> str:
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


def _extract_link(text: str) -> str:
    """从工具输出中提取飞书/lark链接"""
    import re
    match = re.search(r'https?://[^\s]*(?:feishu\.cn|larksuite\.com)[^\s\)\"]*', text)
    return match.group(0) if match else ""


def _summarize_output(tool_name: str, output: str, success: bool) -> str:
    """从工具返回值中提取摘要，按工具类型智能提取"""
    if not output:
        return ""

    # 失败时直接提取错误原因
    if not success:
        text = output.split("[系统提示]")[0].strip()
        return f"❌ {text[:50]}" if len(text) > 50 else f"❌ {text}"

    text = output.split("[系统提示]")[0].strip()
    link = _extract_link(text)

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
    import re
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
    import json as _json
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


def _make_plan_cb(chat_id: str):
    def _on_plan(steps: list[str]):
        lines = ["📋 执行计划:"]
        for i, step in enumerate(steps, 1):
            lines.append(f"{i}. {step}")
        send_reply(chat_id, "\n".join(lines))
    return _on_plan


def main():
    import config
    config.validate()
    hooks.load_custom_hooks()
    proc = start_event_consumer()
    print("[BOT] Listening for messages...", file=sys.stderr)

    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                _executor.submit(handle_message, event)
            except json.JSONDecodeError:
                logger.log_error("system", "bot", "json_parse", stderr=f"Bad line: {line[:200]}")
    except KeyboardInterrupt:
        print("\n[BOT] Shutting down...", file=sys.stderr)
    finally:
        _executor.shutdown(wait=False)
        proc.stdin.close()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
