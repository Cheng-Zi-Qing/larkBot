from __future__ import annotations

import inspect
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Callable

import config
import hooks
import logger
from hooks import HookContext


@dataclass
class ToolResult:
    output: str
    success: bool
    cached: bool = False


@dataclass
class ToolDef:
    name: str
    description: str
    identity: str  # "user", "bot", or "" for non-lark tools
    claude_schema: dict[str, Any]
    build_command: Callable[[dict], list[str]] | None = None
    python_func: Callable[[dict], str] | None = None


TOOL_REGISTRY: dict[str, ToolDef] = {}


def register(tool: ToolDef):
    TOOL_REGISTRY[tool.name] = tool
    return tool


def get_tool_definitions() -> list[dict]:
    from persona_tools import PERSONA_TOOLS
    allowed = PERSONA_TOOLS.get(config.get_persona())
    if allowed is None:
        return [t.claude_schema for t in TOOL_REGISTRY.values()]
    allowed_set = set(allowed)
    return [t.claude_schema for t in TOOL_REGISTRY.values() if t.name in allowed_set]


def execute_tool(request_id: str, tool_name: str, tool_input: dict) -> ToolResult:
    if tool_name not in TOOL_REGISTRY:
        return ToolResult(output=f"Unknown tool: {tool_name}", success=False)

    tool_def = TOOL_REGISTRY[tool_name]

    ctx = HookContext(request_id=request_id, tool_name=tool_name, tool_input=tool_input)
    hook_result = hooks.fire("before_tool", ctx)
    if hook_result.skip:
        return ToolResult(output=hook_result.override_output, success=True, cached=True)

    if tool_def.python_func:
        return _execute_python_tool(request_id, tool_def, tool_input, ctx)
    return _execute_cli_tool(request_id, tool_def, tool_input, ctx)


def _execute_python_tool(
    request_id: str, tool_def: ToolDef, tool_input: dict, ctx: HookContext,
) -> ToolResult:
    start = time.monotonic()
    try:
        context = {"request_id": request_id, "chat_id": ctx.chat_id, "persona": config.get_persona()}
        sig = inspect.signature(tool_def.python_func)
        if len(sig.parameters) >= 2:
            output = tool_def.python_func(tool_input, context)
        else:
            output = tool_def.python_func(tool_input)
        duration_ms = (time.monotonic() - start) * 1000
        logger.log_tool_call(
            request_id, tool_def.name, tool_input,
            [f"python:{tool_def.name}"], _FakeProc(0, output, ""), duration_ms,
        )
        hooks.fire("after_tool", ctx.with_result(_FakeProc(0, output, ""), duration_ms))
        return ToolResult(output=output, success=True)
    except Exception as e:
        duration_ms = (time.monotonic() - start) * 1000
        error_msg = f"{type(e).__name__}: {e}"
        logger.log_error(request_id, tool_def.name, type(e).__name__, stderr=error_msg)
        hooks.fire("on_error", ctx.with_error(type(e).__name__))
        return ToolResult(output=error_msg, success=False)


class _FakeProc:
    """Mimics subprocess.CompletedProcess for logger compatibility."""
    def __init__(self, returncode: int, stdout: str, stderr: str):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _execute_cli_tool(
    request_id: str, tool_def: ToolDef, tool_input: dict, ctx: HookContext,
) -> ToolResult:
    cmd = tool_def.build_command(tool_input)
    if ctx.extra_flags:
        cmd.extend(ctx.extra_flags)

    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=config.TOOL_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        duration_ms = (time.monotonic() - start) * 1000
        logger.log_error(request_id, tool_def.name, "TimeoutError", duration_ms=duration_ms)
        hooks.fire("on_error", ctx.with_error("TimeoutError"))
        return ToolResult(output="Tool call timed out", success=False)

    duration_ms = (time.monotonic() - start) * 1000

    logger.log_tool_call(request_id, tool_def.name, tool_input, cmd, proc, duration_ms)

    if proc.returncode != 0:
        error_ctx = ctx.with_result(proc, duration_ms)

        if proc.returncode == 10:
            logger.log_error(
                request_id, tool_def.name, "HighRiskBlocked",
                stderr=proc.stderr, exit_code=10,
            )
        else:
            logger.log_error(
                request_id, tool_def.name, "LarkCLIError",
                stderr=proc.stderr, exit_code=proc.returncode,
            )

        hook_result = hooks.fire("on_error", error_ctx)
        if hook_result.retry and ctx.retry_count < config.MAX_RETRIES:
            ctx.retry_count += 1
            return _execute_cli_tool(request_id, tool_def, tool_input, ctx)

        return ToolResult(
            output=f"Error (exit {proc.returncode}): {proc.stderr[:500]}",
            success=False,
        )

    result_ctx = ctx.with_result(proc, duration_ms)
    hooks.fire("after_tool", result_ctx)

    return ToolResult(output=proc.stdout, success=True)


# ---------------------------------------------------------------------------
# Tool definitions (22 tools)
# ---------------------------------------------------------------------------

def _schema(name: str, desc: str, props: dict, required: list[str] | None = None) -> dict:
    schema: dict = {
        "name": name,
        "description": desc,
        "input_schema": {
            "type": "object",
            "properties": props,
        },
    }
    if required:
        schema["input_schema"]["required"] = required
    return schema


# --- Messages ---

register(ToolDef(
    name="search_messages",
    description="搜索飞书消息",
    identity="user",
    claude_schema=_schema("search_messages", "Search messages across chats", {
        "query": {"type": "string", "description": "Search keyword"},
        "chat_id": {"type": "string", "description": "Optional: limit to a specific chat"},
    }, ["query"]),
    build_command=lambda i: [
        "lark-cli", "im", "+messages-search", "--as", "user", "--format", "json",
        "--query", i["query"],
        *(["--chat-id", i["chat_id"]] if i.get("chat_id") else []),
    ],
))

register(ToolDef(
    name="get_chat_history",
    description="获取群聊/私聊的历史消息",
    identity="user",
    claude_schema=_schema("get_chat_history", "Get message history of a chat", {
        "chat_id": {"type": "string", "description": "Chat ID"},
        "page_size": {"type": "integer", "description": "Number of messages (default 20)"},
    }, ["chat_id"]),
    build_command=lambda i: [
        "lark-cli", "im", "+chat-messages-list", "--as", "user", "--format", "json",
        "--chat-id", i["chat_id"],
        *(["--page-size", str(i["page_size"])] if i.get("page_size") else []),
    ],
))

register(ToolDef(
    name="send_message",
    description="向群聊/私聊发送消息",
    identity="bot",
    claude_schema=_schema("send_message", "Send a text message to a chat", {
        "chat_id": {"type": "string", "description": "Target chat ID"},
        "text": {"type": "string", "description": "Message text"},
    }, ["chat_id", "text"]),
    build_command=lambda i: [
        "lark-cli", "im", "+messages-send", "--as", "bot", "--format", "json",
        "--chat-id", i["chat_id"], "--text", i["text"],
    ],
))

register(ToolDef(
    name="reply_message",
    description="回复指定消息",
    identity="bot",
    claude_schema=_schema("reply_message", "Reply to a specific message", {
        "message_id": {"type": "string", "description": "Message ID to reply to"},
        "text": {"type": "string", "description": "Reply text"},
    }, ["message_id", "text"]),
    build_command=lambda i: [
        "lark-cli", "im", "+messages-reply", "--as", "bot", "--format", "json",
        "--message-id", i["message_id"], "--text", i["text"],
    ],
))

register(ToolDef(
    name="search_chats",
    description="搜索群聊",
    identity="user",
    claude_schema=_schema("search_chats", "Search for chats/groups by name", {
        "query": {"type": "string", "description": "Search keyword"},
    }, ["query"]),
    build_command=lambda i: [
        "lark-cli", "im", "+chat-search", "--as", "user", "--format", "json",
        "--query", i["query"],
    ],
))

# --- Docs ---

register(ToolDef(
    name="create_doc",
    description="创建飞书文档",
    identity="user",
    claude_schema=_schema("create_doc", "Create a new Lark document with markdown content", {
        "title": {"type": "string", "description": "Document title"},
        "content": {"type": "string", "description": "Document body in markdown"},
    }, ["title", "content"]),
    build_command=lambda i: [
        "lark-cli", "docs", "+create", "--as", "user",
        "--api-version", "v2", "--doc-format", "markdown",
        "--content", f"<title>{i['title']}</title>\n{i['content']}",
    ],
))

register(ToolDef(
    name="read_doc",
    description="读取飞书文档内容",
    identity="user",
    claude_schema=_schema("read_doc", "Read a Lark document by its ID or URL", {
        "doc": {"type": "string", "description": "Document ID or URL"},
    }, ["doc"]),
    build_command=lambda i: [
        "lark-cli", "docs", "+fetch", "--as", "user",
        "--api-version", "v2", "--doc", i["doc"],
    ],
))

register(ToolDef(
    name="search_docs",
    description="搜索飞书文档/云盘文件",
    identity="user",
    claude_schema=_schema("search_docs", "Search documents and files in Lark Drive", {
        "query": {"type": "string", "description": "Search keyword"},
    }, ["query"]),
    build_command=lambda i: [
        "lark-cli", "drive", "files", "search", "--as", "user", "--format", "json",
        "--query", i["query"],
    ],
))

# --- Sheets / Base ---

register(ToolDef(
    name="read_table",
    description="读取多维表格记录",
    identity="user",
    claude_schema=_schema("read_table", "Search records in a Bitable table", {
        "base_token": {"type": "string", "description": "Bitable app token"},
        "table_id": {"type": "string", "description": "Table ID"},
        "filter": {"type": "string", "description": "Optional filter expression"},
    }, ["base_token", "table_id"]),
    build_command=lambda i: [
        "lark-cli", "base", "+record-search", "--as", "user", "--format", "json",
        "--base-token", i["base_token"], "--table-id", i["table_id"],
        *(["--filter", i["filter"]] if i.get("filter") else []),
    ],
))

register(ToolDef(
    name="write_table",
    description="向多维表格写入记录",
    identity="user",
    claude_schema=_schema("write_table", "Create records in a Bitable table", {
        "base_token": {"type": "string", "description": "Bitable app token"},
        "table_id": {"type": "string", "description": "Table ID"},
        "records": {"type": "string", "description": "JSON array of records to create"},
    }, ["base_token", "table_id", "records"]),
    build_command=lambda i: [
        "lark-cli", "base", "+record-create", "--as", "user", "--format", "json",
        "--base-token", i["base_token"], "--table-id", i["table_id"],
        "--records", i["records"],
    ],
))

register(ToolDef(
    name="query_table",
    description="查询多维表格数据",
    identity="user",
    claude_schema=_schema("query_table", "Run a data query on a Bitable table", {
        "base_token": {"type": "string", "description": "Bitable app token"},
        "table_id": {"type": "string", "description": "Table ID"},
        "query": {"type": "string", "description": "Query expression"},
    }, ["base_token", "table_id"]),
    build_command=lambda i: [
        "lark-cli", "base", "+data-query", "--as", "user", "--format", "json",
        "--base-token", i["base_token"], "--table-id", i["table_id"],
        *(["--query", i["query"]] if i.get("query") else []),
    ],
))

register(ToolDef(
    name="read_sheet",
    description="读取电子表格数据",
    identity="user",
    claude_schema=_schema("read_sheet", "Read data from a spreadsheet", {
        "spreadsheet_token": {"type": "string", "description": "Spreadsheet token"},
        "sheet_id": {"type": "string", "description": "Sheet ID"},
        "range": {"type": "string", "description": "Optional cell range (e.g. A1:D10)"},
    }, ["spreadsheet_token", "sheet_id"]),
    build_command=lambda i: [
        "lark-cli", "sheets", "+read", "--as", "user", "--format", "json",
        "--spreadsheet-token", i["spreadsheet_token"], "--sheet-id", i["sheet_id"],
        *(["--range", i["range"]] if i.get("range") else []),
    ],
))

# --- Calendar ---

register(ToolDef(
    name="get_agenda",
    description="查看用户日历日程",
    identity="user",
    claude_schema=_schema("get_agenda", "Get the user's calendar agenda for today or a date range", {
        "start": {"type": "string", "description": "Start datetime (ISO 8601), default today"},
        "end": {"type": "string", "description": "End datetime (ISO 8601), default today"},
    }),
    build_command=lambda i: [
        "lark-cli", "calendar", "+agenda", "--as", "user", "--format", "json",
        *(["--start", i["start"]] if i.get("start") else []),
        *(["--end", i["end"]] if i.get("end") else []),
    ],
))

register(ToolDef(
    name="create_event",
    description="创建日历事件",
    identity="user",
    claude_schema=_schema("create_event", "Create a calendar event", {
        "summary": {"type": "string", "description": "Event title"},
        "start": {"type": "string", "description": "Start datetime (ISO 8601)"},
        "end": {"type": "string", "description": "End datetime (ISO 8601)"},
        "description": {"type": "string", "description": "Optional event description"},
    }, ["summary", "start", "end"]),
    build_command=lambda i: [
        "lark-cli", "calendar", "+create", "--as", "user", "--format", "json",
        "--summary", i["summary"], "--start", i["start"], "--end", i["end"],
        *(["--description", i["description"]] if i.get("description") else []),
    ],
))

register(ToolDef(
    name="check_freebusy",
    description="查询用户忙闲状态",
    identity="user",
    claude_schema=_schema("check_freebusy", "Check if a user is free or busy in a time range", {
        "user_id": {"type": "string", "description": "User ID to check"},
        "start": {"type": "string", "description": "Start datetime (ISO 8601)"},
        "end": {"type": "string", "description": "End datetime (ISO 8601)"},
    }, ["user_id", "start", "end"]),
    build_command=lambda i: [
        "lark-cli", "calendar", "+freebusy", "--as", "user", "--format", "json",
        "--user-id", i["user_id"], "--start", i["start"], "--end", i["end"],
    ],
))

# --- Tasks ---

register(ToolDef(
    name="get_my_tasks",
    description="获取用户的任务列表",
    identity="user",
    claude_schema=_schema("get_my_tasks", "Get the user's task list", {}),
    build_command=lambda i: [
        "lark-cli", "task", "+get-my-tasks", "--as", "user", "--format", "json",
    ],
))

register(ToolDef(
    name="create_task",
    description="创建任务",
    identity="user",
    claude_schema=_schema("create_task", "Create a new task", {
        "summary": {"type": "string", "description": "Task summary"},
        "due": {"type": "string", "description": "Optional due datetime (ISO 8601)"},
    }, ["summary"]),
    build_command=lambda i: [
        "lark-cli", "task", "+create", "--as", "user", "--format", "json",
        "--summary", i["summary"],
        *(["--due", i["due"]] if i.get("due") else []),
    ],
))

register(ToolDef(
    name="search_tasks",
    description="搜索任务",
    identity="user",
    claude_schema=_schema("search_tasks", "Search for tasks", {
        "query": {"type": "string", "description": "Search keyword"},
    }, ["query"]),
    build_command=lambda i: [
        "lark-cli", "task", "+search", "--as", "user", "--format", "json",
        "--query", i["query"],
    ],
))

# --- Mail ---

register(ToolDef(
    name="search_mail",
    description="搜索邮件",
    identity="user",
    claude_schema=_schema("search_mail", "Search emails", {
        "query": {"type": "string", "description": "Search keyword"},
    }, ["query"]),
    build_command=lambda i: [
        "lark-cli", "mail", "+search", "--as", "user", "--format", "json",
        "--query", i["query"],
    ],
))

# --- Contacts ---

register(ToolDef(
    name="search_user",
    description="搜索通讯录用户",
    identity="user",
    claude_schema=_schema("search_user", "Search for users in the company directory", {
        "query": {"type": "string", "description": "Name or keyword to search"},
    }, ["query"]),
    build_command=lambda i: [
        "lark-cli", "contact", "+search-user", "--as", "user", "--format", "json",
        "--query", i["query"],
    ],
))

# --- Meetings ---

register(ToolDef(
    name="search_meetings",
    description="搜索会议记录",
    identity="user",
    claude_schema=_schema("search_meetings", "Search for video conference meetings", {
        "start": {"type": "string", "description": "Start datetime (ISO 8601)"},
        "end": {"type": "string", "description": "End datetime (ISO 8601)"},
    }, ["start", "end"]),
    build_command=lambda i: [
        "lark-cli", "vc", "+search", "--as", "user", "--format", "json",
        "--start", i["start"], "--end", i["end"],
    ],
))

# --- Web tools are registered in web_tools.py ---
