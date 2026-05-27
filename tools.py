from __future__ import annotations

import inspect
import json
import re
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
    category: str = "read"  # read | write | communicate | organize | research
    label: str = ""  # Chinese display label for progress notifications
    build_command: Callable[[dict], list[str]] | None = None
    python_func: Callable[[dict], str] | None = None


TOOL_REGISTRY: dict[str, ToolDef] = {}

AUDIT_TOOLS: dict[str, str] = {
    "create_doc": "create",
    "edit_doc": "update",
    "write_table": "create",
    "base_create": "create",
    "table_create": "create",
    "field_create": "create",
    "record_batch_create": "create",
    "record_batch_update": "update",
    "record_upsert": "create",
    "record_delete": "delete",
    "record_upload_attachment": "create",
    "create_event": "create",
    "update_event": "update",
    "create_task": "create",
    "update_task": "update",
    "complete_task": "update",
    "comment_task": "create",
    "send_message": "create",
    "reply_message": "create",
    "send_mail": "create",
    "reply_mail": "create",
    "drive_upload": "create",
    "drive_import": "create",
    "drive_create_folder": "create",
    "drive_move": "update",
    "drive_delete": "delete",
    "drive_comment": "create",
    "wiki_create_node": "create",
    "wiki_move": "update",
    "create_markdown": "create",
    "overwrite_markdown": "update",
    "patch_markdown": "update",
    "create_slides": "create",
    "create_sheet": "create",
    "append_sheet": "update",
}


def register(tool: ToolDef):
    TOOL_REGISTRY[tool.name] = tool
    return tool


def get_tool_definitions() -> list[dict]:
    from persona_tools import PERSONA_CATEGORIES
    categories = PERSONA_CATEGORIES.get(config.get_persona())
    if categories is None:
        return [t.claude_schema for t in TOOL_REGISTRY.values()]
    return [t.claude_schema for t in TOOL_REGISTRY.values() if t.category in categories]


def get_tool_labels() -> dict[str, str]:
    """Dynamically build tool_name → label mapping from TOOL_REGISTRY."""
    return {name: td.label for name, td in TOOL_REGISTRY.items() if td.label}


def _extract_doc_id(tool_name: str, output: str) -> tuple[str | None, str | None]:
    try:
        data = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return None, None

    if not isinstance(data, dict):
        return None, None

    inner = data.get("data", data)

    if tool_name == "create_doc":
        doc = inner.get("document", inner)
        doc_id = doc.get("document_id") or doc.get("doc_token")
        url = doc.get("url")
        if doc_id and not url:
            url = f"https://wvixbzgc0u7.feishu.cn/docx/{doc_id}"
        return doc_id, url

    if tool_name == "write_table":
        record = inner.get("record", inner)
        return record.get("record_id"), None

    if tool_name == "create_event":
        event = inner.get("event", inner)
        return event.get("event_id"), None

    if tool_name == "create_task":
        task = inner.get("task", inner)
        return task.get("guid") or task.get("task_id"), None

    if tool_name in ("send_message", "reply_message"):
        return inner.get("message_id"), None

    return None, None


def _audit_if_needed(
    tool_name: str, tool_input: dict, ctx: HookContext,
    success: bool, output: str, duration_ms: float, error: str | None = None,
):
    operation = AUDIT_TOOLS.get(tool_name)
    if not operation:
        return
    output_id, output_url = _extract_doc_id(tool_name, output) if success else (None, None)
    logger.log_doc_audit(
        request_id=ctx.request_id or "",
        chat_id=ctx.chat_id or "",
        user_id=ctx.user_id or "",
        tool_name=tool_name,
        operation=operation,
        tool_input=tool_input,
        success=success,
        output_id=output_id,
        output_url=output_url,
        duration_ms=duration_ms,
        error=error,
    )


def execute_tool(
    request_id: str, tool_name: str, tool_input: dict,
    chat_id: str = "", user_id: str = "",
) -> ToolResult:
    if tool_name not in TOOL_REGISTRY:
        return ToolResult(output=f"Unknown tool: {tool_name}", success=False)

    tool_def = TOOL_REGISTRY[tool_name]

    ctx = HookContext(
        request_id=request_id, chat_id=chat_id, user_id=user_id,
        tool_name=tool_name, tool_input=tool_input,
    )
    hook_result = hooks.fire("before_tool", ctx)
    if hook_result.skip:
        return ToolResult(output=hook_result.override_output, success=True, cached=True)

    # Short-term cache: check before executing
    import memory
    cache_key = memory.build_cache_key(tool_name, tool_input)
    if cache_key:
        session_id = memory.get_current_session_id()
        cached_value = memory.get_cache(cache_key, session_id)
        if cached_value:
            return ToolResult(output=cached_value + "\n[来自缓存]", success=True, cached=True)

    if tool_def.python_func:
        result = _execute_python_tool(request_id, tool_def, tool_input, ctx)
    else:
        result = _execute_cli_tool(request_id, tool_def, tool_input, ctx)

    # Short-term cache: store on success
    if cache_key and result.success and not result.cached:
        memory.set_cache(cache_key, result.output, session_id)

    # Document index: async index on doc tool success
    if tool_name in memory._DOC_TOOLS and result.success and not result.cached:
        memory.try_index_document(tool_name, tool_input, result.output)

    # Doc write failure: hint LLM to output content directly to user
    _DOC_WRITE_TOOLS = (
        "create_doc", "edit_doc", "create_markdown", "overwrite_markdown",
        "patch_markdown", "create_slides", "create_sheet",
    )
    if not result.success and tool_name in _DOC_WRITE_TOOLS:
        result.output += (
            "\n[系统提示] 文档写入失败。请将准备好的内容直接以文本形式回复给用户，"
            "不要重试写入操作。"
        )

    return result


def _execute_python_tool(
    request_id: str, tool_def: ToolDef, tool_input: dict, ctx: HookContext,
) -> ToolResult:
    start = time.monotonic()
    try:
        context = {
            "request_id": request_id,
            "chat_id": ctx.chat_id,
            "user_id": ctx.user_id,
            "persona": config.get_persona(),
        }
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
        _audit_if_needed(tool_def.name, tool_input, ctx, True, output, duration_ms)
        return ToolResult(output=output, success=True)
    except Exception as e:
        duration_ms = (time.monotonic() - start) * 1000
        error_msg = f"{type(e).__name__}: {e}"
        logger.log_error(request_id, tool_def.name, type(e).__name__, stderr=error_msg)
        hooks.fire("on_error", ctx.with_error(type(e).__name__))
        _audit_if_needed(tool_def.name, tool_input, ctx, False, "", duration_ms, error=error_msg)
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
    try:
        cmd = tool_def.build_command(tool_input)
    except KeyError as e:
        missing_param = e.args[0] if e.args else "unknown"
        error_msg = f"Missing required parameter: {missing_param}"
        logger.log_error(request_id, tool_def.name, "MissingParam", stderr=error_msg)
        return ToolResult(output=error_msg, success=False)

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

        _audit_if_needed(
            tool_def.name, tool_input, ctx, False, "",
            duration_ms, error=proc.stderr[:500],
        )
        return ToolResult(
            output=f"Error (exit {proc.returncode}): {proc.stderr[:500]}",
            success=False,
        )

    result_ctx = ctx.with_result(proc, duration_ms)
    hooks.fire("after_tool", result_ctx)

    _audit_if_needed(tool_def.name, tool_input, ctx, True, proc.stdout, duration_ms)
    return ToolResult(output=proc.stdout, success=True)


# ---------------------------------------------------------------------------
# Tool definitions
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
    label="搜索消息",
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
    label="读取聊天记录",
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
    category="communicate",
    label="发送消息",
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
    category="communicate",
    label="回复消息",
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
    label="搜索会话",
    claude_schema=_schema("search_chats", "Search for chats/groups by name", {
        "query": {"type": "string", "description": "Search keyword"},
    }, ["query"]),
    build_command=lambda i: [
        "lark-cli", "im", "+chat-search", "--as", "user", "--format", "json",
        "--query", i["query"],
    ],
))

# ========================== Docs ==========================

register(ToolDef(
    name="create_doc",
    description=(
        "创建飞书文档。默认使用 XML 格式（支持富文本），也可用 markdown。"
        "链接语法：XML 用 <a href=\"URL\">文字</a>，Markdown 用 [文字](URL)。"
        "链接预览卡片：<a type=\"url-preview\" href=\"URL\">标题</a>。"
    ),
    identity="user",
    category="write",
    label="创建文档",
    claude_schema=_schema("create_doc", "Create a new Lark document. Default XML format supports rich elements; use doc_format=markdown for simple docs. Links: <a href=\"URL\">text</a> in XML, [text](url) in markdown.", {
        "title": {"type": "string", "description": "Document title"},
        "content": {"type": "string", "description": "Document body. XML (default): use <p>, <h1>, <a href>, <table> etc. Markdown: standard syntax."},
        "doc_format": {
            "type": "string",
            "description": "Content format: xml (default, richer) | markdown",
            "enum": ["xml", "markdown"],
        },
    }, ["title", "content"]),
    build_command=lambda i: [
        "lark-cli", "docs", "+create", "--as", "user",
        "--api-version", "v2",
        "--content", f"<title>{i['title']}</title>\n{i['content']}" if not i.get("doc_format") or i.get("doc_format") == "xml" else f"# {i['title']}\n\n{i['content']}",
    ] + (["--doc-format", i["doc_format"]] if i.get("doc_format") else []),
))

register(ToolDef(
    name="read_doc",
    description="读取飞书文档内容",
    identity="user",
    label="读取文档",
    claude_schema=_schema("read_doc", "Read a Lark document by its ID or URL", {
        "doc": {"type": "string", "description": "Document ID or URL"},
    }, ["doc"]),
    build_command=lambda i: [
        "lark-cli", "docs", "+fetch", "--as", "user",
        "--api-version", "v2", "--doc", i["doc"],
    ],
))

register(ToolDef(
    name="edit_doc",
    description=(
        "编辑已有飞书文档。支持追加、覆盖、文本替换三种模式。"
        "链接格式：XML 模式用 <a href=\"URL\">文字</a>，Markdown 模式用 [文字](URL)。"
        "链接预览卡片：<a type=\"url-preview\" href=\"URL\">标题</a>。"
        "书签块：<bookmark name=\"标题\" href=\"URL\"></bookmark>。"
        "注意：str_replace 的 pattern 在 XML 模式下只能行内匹配，跨行匹配请用 doc_format=markdown。"
    ),
    identity="user",
    category="write",
    label="编辑文档",
    claude_schema=_schema("edit_doc", "Edit an existing Lark document. Commands: append (add to end), overwrite (replace all), str_replace (find-and-replace text). For links use <a href=\"URL\">text</a> in XML or [text](url) in markdown.", {
        "doc": {"type": "string", "description": "Document ID or URL"},
        "content": {"type": "string", "description": "New content (XML default, or markdown if doc_format=markdown). Links: <a href=\"URL\">text</a> or [text](url)"},
        "command": {
            "type": "string",
            "description": "Edit command: append | overwrite | str_replace",
            "enum": ["append", "overwrite", "str_replace"],
        },
        "pattern": {"type": "string", "description": "For str_replace: text to find. Supports '前缀...后缀' ellipsis syntax in markdown mode for cross-line matching"},
        "doc_format": {
            "type": "string",
            "description": "Content format: xml (default, supports rich formatting) | markdown (simpler, supports cross-line str_replace)",
            "enum": ["xml", "markdown"],
        },
        "new_title": {"type": "string", "description": "Optional: also update the document title"},
    }, ["doc", "content", "command"]),
    build_command=lambda i: [
        "lark-cli", "docs", "+update", "--as", "user",
        "--api-version", "v2",
        "--doc", i["doc"],
        "--command", i["command"],
        "--content", i["content"],
    ] + (["--doc-format", i["doc_format"]] if i.get("doc_format") else [])
      + (["--pattern", i["pattern"]] if i.get("pattern") else [])
      + (["--new-title", i["new_title"]] if i.get("new_title") else []),
))

register(ToolDef(
    name="search_docs",
    description="搜索飞书文档/云盘文件",
    identity="user",
    label="搜索文档",
    claude_schema=_schema("search_docs", "Search documents and files in Lark Drive", {
        "query": {"type": "string", "description": "Search keyword"},
    }, ["query"]),
    build_command=lambda i: [
        "lark-cli", "docs", "+search", "--as", "user", "--format", "json",
        "--query", i["query"],
    ],
))

register(ToolDef(
    name="doc_insert_media",
    description="向飞书文档中插入图片或文件",
    identity="user",
    category="write",
    label="插入媒体",
    claude_schema=_schema("doc_insert_media", "Insert an image or file into a Lark document", {
        "doc": {"type": "string", "description": "Document ID or URL"},
        "file": {"type": "string", "description": "Local file path to insert"},
        "type": {"type": "string", "description": "Media type: image | file", "enum": ["image", "file"]},
        "selection": {"type": "string", "description": "Optional: insert near this text (plain text or 'start...end')"},
    }, ["doc", "file"]),
    build_command=lambda i: [
        "lark-cli", "docs", "+media-insert", "--as", "user",
        "--doc", i["doc"], "--file", i["file"],
        *(["--type", i["type"]] if i.get("type") else []),
        *(["--selection-with-ellipsis", i["selection"]] if i.get("selection") else []),
    ],
))


# ========================== Sheets / Base ==========================

register(ToolDef(
    name="read_table",
    description="读取多维表格记录",
    identity="user",
    label="读取多维表格",
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
    category="write",
    label="写入多维表格",
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
    label="查询多维表格",
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
    name="base_create",
    description="创建多维表格应用",
    identity="user",
    category="write",
    label="创建多维表格",
    claude_schema=_schema("base_create", "Create a new Bitable base", {
        "name": {"type": "string", "description": "Base name"},
        "folder_token": {"type": "string", "description": "Folder token (optional)"},
    }, ["name"]),
    build_command=lambda i: [
        "lark-cli", "base", "+base-create", "--as", "user",
        "--name", i["name"],
        *(["--folder-token", i["folder_token"]] if i.get("folder_token") else []),
    ],
))

register(ToolDef(
    name="base_get",
    description="获取多维表格应用信息",
    identity="user",
    label="查看多维表格信息",
    claude_schema=_schema("base_get", "Get metadata of a Bitable base", {
        "base_token": {"type": "string", "description": "Base token"},
    }, ["base_token"]),
    build_command=lambda i: [
        "lark-cli", "base", "+base-get", "--as", "user", "--format", "json",
        "--base-token", i["base_token"],
    ],
))

register(ToolDef(
    name="table_list",
    description="列出多维表格中的数据表",
    identity="user",
    label="列出数据表",
    claude_schema=_schema("table_list", "List tables in a Bitable base", {
        "base_token": {"type": "string", "description": "Base token"},
    }, ["base_token"]),
    build_command=lambda i: [
        "lark-cli", "base", "+table-list", "--as", "user", "--format", "json",
        "--base-token", i["base_token"],
    ],
))

register(ToolDef(
    name="table_create",
    description="在多维表格中创建数据表",
    identity="user",
    category="write",
    label="创建数据表",
    claude_schema=_schema("table_create", "Create a table in a Bitable base", {
        "base_token": {"type": "string", "description": "Base token"},
        "name": {"type": "string", "description": "Table name"},
        "fields": {"type": "string", "description": "Field definitions JSON array (optional)"},
    }, ["base_token", "name"]),
    build_command=lambda i: [
        "lark-cli", "base", "+table-create", "--as", "user",
        "--base-token", i["base_token"], "--name", i["name"],
        *(["--fields", i["fields"]] if i.get("fields") else []),
    ],
))

register(ToolDef(
    name="field_list",
    description="列出数据表的字段",
    identity="user",
    label="列出字段",
    claude_schema=_schema("field_list", "List fields (columns) in a Bitable table", {
        "base_token": {"type": "string", "description": "Base token"},
        "table_id": {"type": "string", "description": "Table ID or name"},
    }, ["base_token", "table_id"]),
    build_command=lambda i: [
        "lark-cli", "base", "+field-list", "--as", "user", "--format", "json",
        "--base-token", i["base_token"], "--table-id", i["table_id"],
    ],
))

register(ToolDef(
    name="field_create",
    description="在数据表中创建字段",
    identity="user",
    category="write",
    label="创建字段",
    claude_schema=_schema("field_create", "Create a field (column) in a Bitable table", {
        "base_token": {"type": "string", "description": "Base token"},
        "table_id": {"type": "string", "description": "Table ID or name"},
        "json": {"type": "string", "description": "Field property JSON, e.g. {\"name\":\"Status\",\"type\":\"text\"}"},
    }, ["base_token", "table_id", "json"]),
    build_command=lambda i: [
        "lark-cli", "base", "+field-create", "--as", "user",
        "--base-token", i["base_token"], "--table-id", i["table_id"],
        "--json", i["json"],
    ],
))

register(ToolDef(
    name="record_get",
    description="按 ID 获取多维表格记录",
    identity="user",
    label="获取记录",
    claude_schema=_schema("record_get", "Get one or more records by ID", {
        "base_token": {"type": "string", "description": "Base token"},
        "table_id": {"type": "string", "description": "Table ID or name"},
        "record_id": {"type": "string", "description": "Record ID (or comma-separated IDs)"},
    }, ["base_token", "table_id", "record_id"]),
    build_command=lambda i: [
        "lark-cli", "base", "+record-get", "--as", "user", "--format", "json",
        "--base-token", i["base_token"], "--table-id", i["table_id"],
        "--record-id", i["record_id"],
    ],
))

register(ToolDef(
    name="record_list",
    description="分页列出多维表格记录",
    identity="user",
    label="列出记录",
    claude_schema=_schema("record_list", "List records in a Bitable table (paginated)", {
        "base_token": {"type": "string", "description": "Base token"},
        "table_id": {"type": "string", "description": "Table ID or name"},
        "view_id": {"type": "string", "description": "View ID or name (optional)"},
        "limit": {"type": "integer", "description": "Page size, 1-200 (default 100)"},
    }, ["base_token", "table_id"]),
    build_command=lambda i: [
        "lark-cli", "base", "+record-list", "--as", "user", "--format", "json",
        "--base-token", i["base_token"], "--table-id", i["table_id"],
        *(["--view-id", i["view_id"]] if i.get("view_id") else []),
        *(["--limit", str(i["limit"])] if i.get("limit") else []),
    ],
))

register(ToolDef(
    name="record_batch_create",
    description="批量创建多维表格记录",
    identity="user",
    category="write",
    label="批量创建记录",
    claude_schema=_schema("record_batch_create", "Batch create records in a Bitable table", {
        "base_token": {"type": "string", "description": "Base token"},
        "table_id": {"type": "string", "description": "Table ID or name"},
        "json": {"type": "string", "description": "Batch JSON, e.g. {\"fields\":[\"Title\",\"Status\"],\"rows\":[[\"A\",\"Open\"]]}"},
    }, ["base_token", "table_id", "json"]),
    build_command=lambda i: [
        "lark-cli", "base", "+record-batch-create", "--as", "user",
        "--base-token", i["base_token"], "--table-id", i["table_id"],
        "--json", i["json"],
    ],
))

register(ToolDef(
    name="record_batch_update",
    description="批量更新多维表格记录",
    identity="user",
    category="write",
    label="批量更新记录",
    claude_schema=_schema("record_batch_update", "Batch update records in a Bitable table", {
        "base_token": {"type": "string", "description": "Base token"},
        "table_id": {"type": "string", "description": "Table ID or name"},
        "json": {"type": "string", "description": "Update JSON, e.g. {\"record_id_list\":[\"recXXX\"],\"patch\":{\"Status\":\"Done\"}}"},
    }, ["base_token", "table_id", "json"]),
    build_command=lambda i: [
        "lark-cli", "base", "+record-batch-update", "--as", "user",
        "--base-token", i["base_token"], "--table-id", i["table_id"],
        "--json", i["json"],
    ],
))

register(ToolDef(
    name="record_upsert",
    description="创建或更新多维表格记录",
    identity="user",
    category="write",
    label="更新插入记录",
    claude_schema=_schema("record_upsert", "Create or update a single record (upsert)", {
        "base_token": {"type": "string", "description": "Base token"},
        "table_id": {"type": "string", "description": "Table ID or name"},
        "json": {"type": "string", "description": "Record JSON, e.g. {\"Name\":\"Alice\"}"},
        "record_id": {"type": "string", "description": "Record ID for update (omit to create)"},
    }, ["base_token", "table_id", "json"]),
    build_command=lambda i: [
        "lark-cli", "base", "+record-upsert", "--as", "user",
        "--base-token", i["base_token"], "--table-id", i["table_id"],
        "--json", i["json"],
        *(["--record-id", i["record_id"]] if i.get("record_id") else []),
    ],
))

register(ToolDef(
    name="record_delete",
    description="删除多维表格记录（危险操作）",
    identity="user",
    category="organize",
    label="删除记录",
    claude_schema=_schema("record_delete", "Delete one or more records by ID (DANGEROUS)", {
        "base_token": {"type": "string", "description": "Base token"},
        "table_id": {"type": "string", "description": "Table ID or name"},
        "record_id": {"type": "string", "description": "Record ID(s), comma-separated"},
    }, ["base_token", "table_id", "record_id"]),
    build_command=lambda i: [
        "lark-cli", "base", "+record-delete", "--as", "user",
        "--base-token", i["base_token"], "--table-id", i["table_id"],
        "--record-id", i["record_id"], "--yes",
    ],
))

register(ToolDef(
    name="record_upload_attachment",
    description="上传附件到多维表格记录",
    identity="user",
    category="write",
    label="上传附件",
    claude_schema=_schema("record_upload_attachment", "Upload files to a Bitable attachment field", {
        "base_token": {"type": "string", "description": "Base token"},
        "table_id": {"type": "string", "description": "Table ID or name"},
        "record_id": {"type": "string", "description": "Record ID"},
        "field_id": {"type": "string", "description": "Attachment field ID or name"},
        "file": {"type": "string", "description": "Local file path"},
    }, ["base_token", "table_id", "record_id", "field_id", "file"]),
    build_command=lambda i: [
        "lark-cli", "base", "+record-upload-attachment", "--as", "user",
        "--base-token", i["base_token"], "--table-id", i["table_id"],
        "--record-id", i["record_id"], "--field-id", i["field_id"],
        "--file", i["file"],
    ],
))

register(ToolDef(
    name="view_list",
    description="列出数据表的视图",
    identity="user",
    label="列出视图",
    claude_schema=_schema("view_list", "List views in a Bitable table", {
        "base_token": {"type": "string", "description": "Base token"},
        "table_id": {"type": "string", "description": "Table ID or name"},
    }, ["base_token", "table_id"]),
    build_command=lambda i: [
        "lark-cli", "base", "+view-list", "--as", "user", "--format", "json",
        "--base-token", i["base_token"], "--table-id", i["table_id"],
    ],
))

register(ToolDef(
    name="data_query",
    description="用 JSON DSL 查询多维表格（聚合/过滤/排序）",
    identity="user",
    label="数据查询",
    claude_schema=_schema("data_query", "Query Bitable data with JSON DSL (aggregation, filter, sort)", {
        "base_token": {"type": "string", "description": "Base token"},
        "dsl": {"type": "string", "description": "Query JSON DSL (LiteQuery Protocol)"},
    }, ["base_token", "dsl"]),
    build_command=lambda i: [
        "lark-cli", "base", "+data-query", "--as", "user", "--format", "json",
        "--base-token", i["base_token"], "--dsl", i["dsl"],
    ],
))

register(ToolDef(
    name="read_sheet",
    description="读取电子表格数据",
    identity="user",
    label="读取电子表格",
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

register(ToolDef(
    name="create_sheet",
    description="创建电子表格",
    identity="user",
    category="write",
    label="创建电子表格",
    claude_schema=_schema("create_sheet", "Create a spreadsheet with optional headers and data", {
        "title": {"type": "string", "description": "Spreadsheet title"},
        "headers": {"type": "string", "description": "Optional: header row as JSON array, e.g. [\"Name\",\"Age\"]"},
        "data": {"type": "string", "description": "Optional: initial data as JSON 2D array"},
        "folder_token": {"type": "string", "description": "Optional: target folder token"},
    }, ["title"]),
    build_command=lambda i: [
        "lark-cli", "sheets", "+create", "--as", "user",
        "--title", i["title"],
        *(["--headers", i["headers"]] if i.get("headers") else []),
        *(["--data", i["data"]] if i.get("data") else []),
        *(["--folder-token", i["folder_token"]] if i.get("folder_token") else []),
    ],
))

register(ToolDef(
    name="append_sheet",
    description="向电子表格追加行",
    identity="user",
    category="write",
    label="追加表格数据",
    claude_schema=_schema("append_sheet", "Append rows to a spreadsheet", {
        "spreadsheet_token": {"type": "string", "description": "Spreadsheet token"},
        "sheet_id": {"type": "string", "description": "Sheet ID"},
        "range": {"type": "string", "description": "Append range, e.g. A1:D1"},
        "values": {"type": "string", "description": "2D array JSON of row values"},
    }, ["spreadsheet_token", "sheet_id", "range", "values"]),
    build_command=lambda i: [
        "lark-cli", "sheets", "+append", "--as", "user",
        "--spreadsheet-token", i["spreadsheet_token"],
        "--sheet-id", i["sheet_id"],
        "--range", i["range"],
        "--values", i["values"],
    ],
))

register(ToolDef(
    name="find_sheet",
    description="在电子表格中查找单元格",
    identity="user",
    label="查找表格数据",
    claude_schema=_schema("find_sheet", "Find cells in a spreadsheet by keyword", {
        "spreadsheet_token": {"type": "string", "description": "Spreadsheet token"},
        "sheet_id": {"type": "string", "description": "Sheet ID"},
        "find": {"type": "string", "description": "Search text"},
        "range": {"type": "string", "description": "Optional: search range (e.g. A1:D100)"},
    }, ["spreadsheet_token", "sheet_id", "find"]),
    build_command=lambda i: [
        "lark-cli", "sheets", "+find", "--as", "user",
        "--spreadsheet-token", i["spreadsheet_token"],
        "--sheet-id", i["sheet_id"],
        "--find", i["find"],
        *(["--range", i["range"]] if i.get("range") else []),
    ],
))


# ========================== Calendar ==========================

register(ToolDef(
    name="get_agenda",
    description="查看用户日历日程",
    identity="user",
    label="查看日程",
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
    category="organize",
    label="创建日程",
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
    label="查询空闲时间",
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

register(ToolDef(
    name="update_event",
    description="更新日历事件（修改标题/时间/描述/参与者）",
    identity="user",
    category="organize",
    label="更新日程",
    claude_schema=_schema("update_event", "Update a calendar event (title, time, attendees)", {
        "event_id": {"type": "string", "description": "Event ID to update"},
        "summary": {"type": "string", "description": "Optional: new event title"},
        "start": {"type": "string", "description": "Optional: new start time (ISO 8601, requires end)"},
        "end": {"type": "string", "description": "Optional: new end time (ISO 8601, requires start)"},
        "description": {"type": "string", "description": "Optional: new description"},
        "add_attendees": {"type": "string", "description": "Optional: comma-separated user/chat/room IDs to add"},
        "remove_attendees": {"type": "string", "description": "Optional: comma-separated IDs to remove"},
    }, ["event_id"]),
    build_command=lambda i: [
        "lark-cli", "calendar", "+update", "--as", "user", "--format", "json",
        "--event-id", i["event_id"],
        *(["--summary", i["summary"]] if i.get("summary") else []),
        *(["--start", i["start"]] if i.get("start") else []),
        *(["--end", i["end"]] if i.get("end") else []),
        *(["--description", i["description"]] if i.get("description") else []),
        *(["--add-attendee-ids", i["add_attendees"]] if i.get("add_attendees") else []),
        *(["--remove-attendee-ids", i["remove_attendees"]] if i.get("remove_attendees") else []),
    ],
))

register(ToolDef(
    name="find_room",
    description="查找可用会议室",
    identity="user",
    label="查找会议室",
    claude_schema=_schema("find_room", "Find available meeting rooms for a time slot", {
        "slot": {"type": "string", "description": "Time slot in start~end format, e.g. 2026-05-22T14:00+08:00~2026-05-22T15:00+08:00"},
        "min_capacity": {"type": "integer", "description": "Optional: minimum room capacity"},
        "building": {"type": "string", "description": "Optional: building name constraint"},
    }, ["slot"]),
    build_command=lambda i: [
        "lark-cli", "calendar", "+room-find", "--as", "user", "--format", "json",
        "--slot", i["slot"],
        *(["--min-capacity", str(i["min_capacity"])] if i.get("min_capacity") else []),
        *(["--building", i["building"]] if i.get("building") else []),
    ],
))

# ========================== Tasks ==========================

register(ToolDef(
    name="get_my_tasks",
    description="获取用户的任务列表",
    identity="user",
    label="查看任务",
    claude_schema=_schema("get_my_tasks", "Get the user's task list", {}),
    build_command=lambda i: [
        "lark-cli", "task", "+get-my-tasks", "--as", "user", "--format", "json",
    ],
))

register(ToolDef(
    name="create_task",
    description="创建任务",
    identity="user",
    category="organize",
    label="创建任务",
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
    label="搜索任务",
    claude_schema=_schema("search_tasks", "Search for tasks", {
        "query": {"type": "string", "description": "Search keyword"},
    }, ["query"]),
    build_command=lambda i: [
        "lark-cli", "task", "+search", "--as", "user", "--format", "json",
        "--query", i["query"],
    ],
))

register(ToolDef(
    name="update_task",
    description="更新任务属性（标题/描述/截止时间）",
    identity="user",
    category="organize",
    label="更新任务",
    claude_schema=_schema("update_task", "Update task attributes", {
        "task_id": {"type": "string", "description": "Task ID"},
        "summary": {"type": "string", "description": "Optional: new task title"},
        "description": {"type": "string", "description": "Optional: new description"},
        "due": {"type": "string", "description": "Optional: new due date (ISO 8601)"},
    }, ["task_id"]),
    build_command=lambda i: [
        "lark-cli", "task", "+update", "--as", "user", "--format", "json",
        "--task-id", i["task_id"],
        *(["--summary", i["summary"]] if i.get("summary") else []),
        *(["--description", i["description"]] if i.get("description") else []),
        *(["--due", i["due"]] if i.get("due") else []),
    ],
))

register(ToolDef(
    name="complete_task",
    description="标记任务完成",
    identity="user",
    category="organize",
    label="完成任务",
    claude_schema=_schema("complete_task", "Mark a task as complete", {
        "task_id": {"type": "string", "description": "Task ID"},
    }, ["task_id"]),
    build_command=lambda i: [
        "lark-cli", "task", "+complete", "--as", "user", "--format", "json",
        "--task-id", i["task_id"],
    ],
))

register(ToolDef(
    name="comment_task",
    description="给任务添加评论",
    identity="user",
    category="organize",
    label="评论任务",
    claude_schema=_schema("comment_task", "Add a comment to a task", {
        "task_id": {"type": "string", "description": "Task ID"},
        "content": {"type": "string", "description": "Comment content"},
    }, ["task_id", "content"]),
    build_command=lambda i: [
        "lark-cli", "task", "+comment", "--as", "user", "--format", "json",
        "--task-id", i["task_id"], "--content", i["content"],
    ],
))

# ========================== Mail ==========================

register(ToolDef(
    name="list_mail",
    description="列出/搜索邮件摘要",
    identity="user",
    label="查看邮件",
    claude_schema=_schema("list_mail", "List or search emails (returns summaries)", {
        "query": {"type": "string", "description": "Search keyword or filter expression"},
        "max": {"type": "integer", "description": "Max results (default 20)"},
    }, ["query"]),
    build_command=lambda i: [
        "lark-cli", "mail", "+triage", "--as", "user", "--format", "json",
        "--query", i["query"],
        *(["--max", str(i["max"])] if i.get("max") else []),
    ],
))

register(ToolDef(
    name="read_mail",
    description="读取单封邮件完整内容",
    identity="user",
    label="读取邮件",
    claude_schema=_schema("read_mail", "Read a single email message by ID", {
        "message_id": {"type": "string", "description": "Mail message ID"},
    }, ["message_id"]),
    build_command=lambda i: [
        "lark-cli", "mail", "+message", "--as", "user",
        "--message-id", i["message_id"],
    ],
))

register(ToolDef(
    name="send_mail",
    description="撰写并发送邮件（默认存草稿，需确认后发送）",
    identity="user",
    category="communicate",
    label="发送邮件",
    claude_schema=_schema("send_mail", "Compose and send an email. Saves as draft unless confirm_send=true.", {
        "to": {"type": "string", "description": "Recipient email(s), comma-separated"},
        "subject": {"type": "string", "description": "Email subject"},
        "body": {"type": "string", "description": "Email body (HTML or plain text)"},
        "cc": {"type": "string", "description": "CC email(s), comma-separated"},
        "confirm_send": {"type": "boolean", "description": "If true, send immediately; otherwise save as draft"},
    }, ["to", "subject", "body"]),
    build_command=lambda i: [
        "lark-cli", "mail", "+send", "--as", "user",
        "--to", i["to"], "--subject", i["subject"], "--body", i["body"],
        *(["--cc", i["cc"]] if i.get("cc") else []),
        *(["--confirm-send"] if i.get("confirm_send") else []),
    ],
))

register(ToolDef(
    name="reply_mail",
    description="回复邮件（默认存草稿，需确认后发送）",
    identity="user",
    category="communicate",
    label="回复邮件",
    claude_schema=_schema("reply_mail", "Reply to an email. Saves as draft unless confirm_send=true.", {
        "message_id": {"type": "string", "description": "Message ID to reply to"},
        "body": {"type": "string", "description": "Reply body (HTML or plain text)"},
        "confirm_send": {"type": "boolean", "description": "If true, send immediately; otherwise save as draft"},
    }, ["message_id", "body"]),
    build_command=lambda i: [
        "lark-cli", "mail", "+reply", "--as", "user",
        "--message-id", i["message_id"], "--body", i["body"],
        *(["--confirm-send"] if i.get("confirm_send") else []),
    ],
))

# --- Contacts ---

register(ToolDef(
    name="search_user",
    description="搜索通讯录用户",
    identity="user",
    label="搜索用户",
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
    label="搜索会议",
    claude_schema=_schema("search_meetings", "Search for video conference meetings", {
        "start": {"type": "string", "description": "Start datetime (ISO 8601)"},
        "end": {"type": "string", "description": "End datetime (ISO 8601)"},
    }, ["start", "end"]),
    build_command=lambda i: [
        "lark-cli", "vc", "+search", "--as", "user", "--format", "json",
        "--start", i["start"], "--end", i["end"],
    ],
))

# ========================== Drive ==========================

register(ToolDef(
    name="drive_upload",
    description="上传文件到云空间",
    identity="user",
    category="write",
    label="上传文件",
    claude_schema=_schema("drive_upload", "Upload a local file to Drive", {
        "file": {"type": "string", "description": "Local file path to upload"},
        "folder_token": {"type": "string", "description": "Target folder token (optional)"},
        "name": {"type": "string", "description": "Override filename in Drive (optional)"},
    }, ["file"]),
    build_command=lambda i: [
        "lark-cli", "drive", "+upload", "--as", "user", "--format", "json",
        "--file", i["file"],
        *(["--folder-token", i["folder_token"]] if i.get("folder_token") else []),
        *(["--name", i["name"]] if i.get("name") else []),
    ],
))

register(ToolDef(
    name="drive_download",
    description="从云空间下载文件",
    identity="user",
    label="下载文件",
    claude_schema=_schema("drive_download", "Download a file from Drive", {
        "file_token": {"type": "string", "description": "File token"},
        "output": {"type": "string", "description": "Local output path (optional)"},
    }, ["file_token"]),
    build_command=lambda i: [
        "lark-cli", "drive", "+download", "--as", "user",
        "--file-token", i["file_token"],
        *(["--output", i["output"]] if i.get("output") else []),
    ],
))

register(ToolDef(
    name="drive_export",
    description="导出云文档为本地文件（docx/pdf等）",
    identity="user",
    label="导出文档",
    claude_schema=_schema("drive_export", "Export a cloud document to a local file format", {
        "token": {"type": "string", "description": "Document token"},
        "doc_type": {"type": "string", "description": "Source doc type: docx, sheet, bitable, mindnote"},
        "file_extension": {"type": "string", "description": "Target format: docx, pdf, xlsx, csv"},
        "output_dir": {"type": "string", "description": "Local output directory (optional)"},
    }, ["token", "doc_type", "file_extension"]),
    build_command=lambda i: [
        "lark-cli", "drive", "+export", "--as", "user",
        "--token", i["token"], "--doc-type", i["doc_type"],
        "--file-extension", i["file_extension"],
        *(["--output-dir", i["output_dir"]] if i.get("output_dir") else []),
    ],
))

register(ToolDef(
    name="drive_import",
    description="导入本地文件为云文档",
    identity="user",
    category="write",
    label="导入文档",
    claude_schema=_schema("drive_import", "Import a local file as a cloud document", {
        "file": {"type": "string", "description": "Local file path"},
        "folder_token": {"type": "string", "description": "Target folder token"},
        "name": {"type": "string", "description": "Document name in Drive (optional)"},
        "type": {"type": "string", "description": "Import type (optional)"},
    }, ["file", "folder_token"]),
    build_command=lambda i: [
        "lark-cli", "drive", "+import", "--as", "user", "--format", "json",
        "--file", i["file"], "--folder-token", i["folder_token"],
        *(["--name", i["name"]] if i.get("name") else []),
        *(["--type", i["type"]] if i.get("type") else []),
    ],
))

register(ToolDef(
    name="drive_create_folder",
    description="在云空间创建文件夹",
    identity="user",
    category="write",
    label="创建文件夹",
    claude_schema=_schema("drive_create_folder", "Create a folder in Drive", {
        "name": {"type": "string", "description": "Folder name"},
        "folder_token": {"type": "string", "description": "Parent folder token (optional, root if omitted)"},
    }, ["name"]),
    build_command=lambda i: [
        "lark-cli", "drive", "+create-folder", "--as", "user", "--format", "json",
        "--name", i["name"],
        *(["--folder-token", i["folder_token"]] if i.get("folder_token") else []),
    ],
))

register(ToolDef(
    name="drive_move",
    description="移动云空间文件/文件夹",
    identity="user",
    category="organize",
    label="移动文件",
    claude_schema=_schema("drive_move", "Move a file or folder in Drive", {
        "file_token": {"type": "string", "description": "File/folder token to move"},
        "folder_token": {"type": "string", "description": "Destination folder token"},
        "type": {"type": "string", "description": "Object type (optional)"},
    }, ["file_token", "folder_token"]),
    build_command=lambda i: [
        "lark-cli", "drive", "+move", "--as", "user", "--format", "json",
        "--file-token", i["file_token"], "--folder-token", i["folder_token"],
        *(["--type", i["type"]] if i.get("type") else []),
    ],
))

register(ToolDef(
    name="drive_delete",
    description="删除云空间文件（危险操作）",
    identity="user",
    category="organize",
    label="删除文件",
    claude_schema=_schema("drive_delete", "Delete a file from Drive (DANGEROUS - irreversible)", {
        "file_token": {"type": "string", "description": "File token to delete"},
        "type": {"type": "string", "description": "Object type (optional)"},
    }, ["file_token"]),
    build_command=lambda i: [
        "lark-cli", "drive", "+delete", "--as", "user", "--format", "json",
        "--file-token", i["file_token"], "--yes",
        *(["--type", i["type"]] if i.get("type") else []),
    ],
))

register(ToolDef(
    name="drive_comment",
    description="给云文档添加评论",
    identity="user",
    category="write",
    label="文档评论",
    claude_schema=_schema("drive_comment", "Add a comment to a document in Drive", {
        "doc": {"type": "string", "description": "Document URL or token"},
        "content": {"type": "string", "description": "Comment content"},
    }, ["doc", "content"]),
    build_command=lambda i: [
        "lark-cli", "drive", "+add-comment", "--as", "user", "--format", "json",
        "--doc", i["doc"], "--content", i["content"],
    ],
))

register(ToolDef(
    name="drive_inspect",
    description="查看云空间文件元信息（类型/权限/token）",
    identity="user",
    label="查看文件信息",
    claude_schema=_schema("drive_inspect", "Inspect a Drive file to get metadata, type, and token", {
        "url": {"type": "string", "description": "File URL or token"},
        "type": {"type": "string", "description": "Object type hint (optional)"},
    }, ["url"]),
    build_command=lambda i: [
        "lark-cli", "drive", "+inspect", "--as", "user", "--format", "json",
        "--url", i["url"],
        *(["--type", i["type"]] if i.get("type") else []),
    ],
))

# ========================== Wiki ==========================

register(ToolDef(
    name="wiki_list_spaces",
    description="列出知识库空间",
    identity="user",
    label="列出知识库",
    claude_schema=_schema("wiki_list_spaces", "List available wiki spaces", {
        "page_size": {"type": "integer", "description": "Results per page (optional)"},
    }, []),
    build_command=lambda i: [
        "lark-cli", "wiki", "+space-list", "--as", "user", "--format", "json",
        "--page-all",
        *(["--page-size", str(i["page_size"])] if i.get("page_size") else []),
    ],
))

register(ToolDef(
    name="wiki_create_node",
    description="在知识库中创建节点",
    identity="user",
    category="write",
    label="创建知识库节点",
    claude_schema=_schema("wiki_create_node", "Create a new node in a wiki space", {
        "space_id": {"type": "string", "description": "Wiki space ID"},
        "title": {"type": "string", "description": "Node title"},
        "parent_node_token": {"type": "string", "description": "Parent node token (optional, root if omitted)"},
        "obj_type": {"type": "string", "description": "Object type (optional)"},
    }, ["space_id", "title"]),
    build_command=lambda i: [
        "lark-cli", "wiki", "+node-create", "--as", "user", "--format", "json",
        "--space-id", i["space_id"], "--title", i["title"],
        *(["--parent-node-token", i["parent_node_token"]] if i.get("parent_node_token") else []),
        *(["--obj-type", i["obj_type"]] if i.get("obj_type") else []),
    ],
))

register(ToolDef(
    name="wiki_get_node",
    description="获取知识库节点详情",
    identity="user",
    label="查看知识库节点",
    claude_schema=_schema("wiki_get_node", "Get details of a wiki node", {
        "token": {"type": "string", "description": "Node token"},
        "space_id": {"type": "string", "description": "Wiki space ID (optional)"},
    }, ["token"]),
    build_command=lambda i: [
        "lark-cli", "wiki", "+node-get", "--as", "user", "--format", "json",
        "--token", i["token"],
        *(["--space-id", i["space_id"]] if i.get("space_id") else []),
    ],
))

register(ToolDef(
    name="wiki_list_nodes",
    description="列出知识库节点列表",
    identity="user",
    label="列出知识库节点",
    claude_schema=_schema("wiki_list_nodes", "List nodes in a wiki space or under a parent node", {
        "space_id": {"type": "string", "description": "Wiki space ID"},
        "parent_node_token": {"type": "string", "description": "Parent node token (optional, lists root if omitted)"},
    }, ["space_id"]),
    build_command=lambda i: [
        "lark-cli", "wiki", "+node-list", "--as", "user", "--format", "json",
        "--space-id", i["space_id"], "--page-all",
        *(["--parent-node-token", i["parent_node_token"]] if i.get("parent_node_token") else []),
    ],
))

register(ToolDef(
    name="wiki_move",
    description="移动知识库节点",
    identity="user",
    category="organize",
    label="移动知识库节点",
    claude_schema=_schema("wiki_move", "Move a wiki node to a different location", {
        "node_token": {"type": "string", "description": "Node token to move"},
        "target_space_id": {"type": "string", "description": "Target wiki space ID"},
        "parent_node_token": {"type": "string", "description": "Target parent node token (optional)"},
    }, ["node_token", "target_space_id"]),
    build_command=lambda i: [
        "lark-cli", "wiki", "+move", "--as", "user", "--format", "json",
        "--node-token", i["node_token"], "--target-space-id", i["target_space_id"],
        *(["--parent-node-token", i["parent_node_token"]] if i.get("parent_node_token") else []),
        "--apply",
    ],
))

# ========================== Markdown ==========================

register(ToolDef(
    name="create_markdown",
    description="创建 Markdown 云文档",
    identity="user",
    category="write",
    label="创建 Markdown",
    claude_schema=_schema("create_markdown", "Create a new Markdown document in Drive", {
        "content": {"type": "string", "description": "Markdown content"},
        "name": {"type": "string", "description": "Document name"},
        "folder_token": {"type": "string", "description": "Target folder token (optional)"},
    }, ["content", "name"]),
    build_command=lambda i: [
        "lark-cli", "markdown", "+create", "--as", "user", "--format", "json",
        "--content", i["content"], "--name", i["name"],
        *(["--folder-token", i["folder_token"]] if i.get("folder_token") else []),
    ],
))

register(ToolDef(
    name="read_markdown",
    description="读取 Markdown 云文档原始内容",
    identity="user",
    label="读取 Markdown",
    claude_schema=_schema("read_markdown", "Fetch the raw Markdown content of a document", {
        "file_token": {"type": "string", "description": "Markdown file token"},
    }, ["file_token"]),
    build_command=lambda i: [
        "lark-cli", "markdown", "+fetch", "--as", "user",
        "--file-token", i["file_token"],
    ],
))

register(ToolDef(
    name="overwrite_markdown",
    description="覆写 Markdown 云文档全部内容",
    identity="user",
    category="write",
    label="覆写 Markdown",
    claude_schema=_schema("overwrite_markdown", "Overwrite the entire content of a Markdown document", {
        "file_token": {"type": "string", "description": "Markdown file token"},
        "content": {"type": "string", "description": "New Markdown content"},
    }, ["file_token", "content"]),
    build_command=lambda i: [
        "lark-cli", "markdown", "+overwrite", "--as", "user", "--format", "json",
        "--file-token", i["file_token"], "--content", i["content"],
    ],
))

register(ToolDef(
    name="patch_markdown",
    description="局部替换 Markdown 云文档内容（按模式匹配替换）",
    identity="user",
    category="write",
    label="修改 Markdown",
    claude_schema=_schema("patch_markdown", "Patch a Markdown document by replacing matched text", {
        "file_token": {"type": "string", "description": "Markdown file token"},
        "pattern": {"type": "string", "description": "Text or regex pattern to match"},
        "content": {"type": "string", "description": "Replacement content"},
        "regex": {"type": "boolean", "description": "Treat pattern as regex (default false)"},
    }, ["file_token", "pattern", "content"]),
    build_command=lambda i: [
        "lark-cli", "markdown", "+patch", "--as", "user", "--format", "json",
        "--file-token", i["file_token"],
        "--pattern", i["pattern"], "--content", i["content"],
        *(["--regex"] if i.get("regex") else []),
    ],
))

# ========================== Slides ==========================

register(ToolDef(
    name="create_slides",
    description="创建演示文稿",
    identity="user",
    category="write",
    label="创建演示文稿",
    claude_schema=_schema("create_slides", "Create a new slide deck", {
        "title": {"type": "string", "description": "Presentation title"},
        "slides": {"type": "string", "description": "Slides content (JSON array or structured text)"},
    }, ["title"]),
    build_command=lambda i: [
        "lark-cli", "slides", "+create", "--as", "user", "--format", "json",
        "--title", i["title"],
        *(["--slides", i["slides"]] if i.get("slides") else []),
    ],
))

# --- Web tools are registered in web_tools.py ---
