from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

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
        subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        print(f"[BOT] Reply timed out for chat {chat_id}", file=sys.stderr)


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


def handle_message(event: dict):
    chat_id = event.get("chat_id", "")
    sender_id = event.get("sender_id", "")
    content = event.get("content", "")
    message_id = event.get("message_id", "")
    request_id = f"req_{uuid.uuid4().hex[:12]}"

    if not content:
        return

    try:
        _process_message(request_id, chat_id, sender_id, content, message_id)
    except Exception as e:
        print(f"[BOT] [{request_id}] Unhandled: {e}", file=sys.stderr)
        try:
            send_reply(chat_id, f"内部错误，请稍后再试。({type(e).__name__})")
        except Exception:
            pass


def _process_message(
    request_id: str, chat_id: str, sender_id: str, content: str, message_id: str,
):
    print(f"[BOT] [{request_id}] From {sender_id}: {content[:80]}", file=sys.stderr)

    if content.startswith("/"):
        handle_command(content, chat_id, request_id)
        return

    try:
        reply = agent.run(request_id, chat_id, content, sender_id=sender_id,
                          on_progress=_make_progress_cb(chat_id),
                          on_plan=_make_plan_cb(chat_id))
        if not reply or not reply.strip():
            reply = "（模型返回为空，请重新描述你的问题）"

        # Routing suggestion: hint user if another persona is better suited
        suggested = config.detect_persona_routing(content)
        if suggested:
            persona_name = config.PERSONAS.get(suggested, {}).get("name", suggested)
            reply += f"\n\n💡 这类问题切换到 /{suggested}（{persona_name}）可能效果更好"

        send_reply(chat_id, reply)
    except Exception as e:
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
                     step: int, total: int, plan_steps: list[str] | None,
                     thought: str = ""):
        nonlocal last_ts
        now = time.time()
        if now - last_ts < 3.0:
            return
        last_ts = now

        lines: list[str] = []

        # Thought line — show model's reasoning (truncated)
        if thought:
            t = thought.strip().replace("\n", " ")
            if len(t) > 80:
                t = t[:77] + "..."
            lines.append(f"💭 {t}")

        # Action line — what tool is being called
        details = []
        for name, inp in zip(tool_names, tool_inputs):
            label = TOOL_LABELS.get(name, name)
            detail = _extract_detail(inp)
            details.append(f"{label} {detail}" if detail else label)

        progress_prefix = f"[{step}/{total}]" if total > 0 else f"[第{step}步]"
        if total > 0 and step > total:
            progress_prefix = f"[额外第{step - total}步]"
        lines.append(f"📎 {progress_prefix} " + "、".join(details))

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
