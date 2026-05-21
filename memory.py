from __future__ import annotations

import json
import re
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import config
import llm
import logger
from tools import ToolDef, register, _schema

_TZ = timezone(timedelta(hours=8))
_SESSION_TIMEOUT = config.SESSION_TIMEOUT_HOURS * 3600

# --- Tool → Base Tag mapping ---

TOOL_TAG_MAP = {
    "get_agenda": "calendar", "create_event": "calendar", "check_freebusy": "calendar",
    "create_doc": "docs", "read_doc": "docs", "search_docs": "docs",
    "send_message": "messaging", "reply_message": "messaging",
    "search_messages": "messaging", "get_chat_history": "messaging", "search_chats": "messaging",
    "read_table": "bitable", "write_table": "bitable", "query_table": "bitable",
    "read_sheet": "bitable",
    "get_my_tasks": "tasks", "create_task": "tasks", "search_tasks": "tasks",
    "search_mail": "mail",
    "search_user": "contacts",
    "search_meetings": "meeting",
    "web_search": "web_search", "web_read": "web_search", "web_research": "web_search",
}

# --- Database ---

_db: sqlite3.Connection | None = None
_db_lock = threading.Lock()

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id    TEXT PRIMARY KEY,
    start_time    INTEGER NOT NULL,
    end_time      INTEGER,
    summary       TEXT,
    base_tags     TEXT,
    people        TEXT,
    topic         TEXT,
    action        TEXT,
    entity        TEXT,
    extra_tags    TEXT,
    message_count INTEGER DEFAULT 0
);

CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts USING fts5(
    summary, people, topic, action, entity, extra_tags,
    content=sessions, content_rowid=rowid
);

CREATE TRIGGER IF NOT EXISTS sessions_ai AFTER INSERT ON sessions BEGIN
    INSERT INTO sessions_fts(rowid, summary, people, topic, action, entity, extra_tags)
    VALUES (new.rowid, new.summary, new.people, new.topic, new.action, new.entity, new.extra_tags);
END;

CREATE TRIGGER IF NOT EXISTS sessions_au AFTER UPDATE ON sessions BEGIN
    DELETE FROM sessions_fts WHERE rowid=old.rowid;
    INSERT INTO sessions_fts(rowid, summary, people, topic, action, entity, extra_tags)
    VALUES (new.rowid, new.summary, new.people, new.topic, new.action, new.entity, new.extra_tags);
END;

CREATE TABLE IF NOT EXISTS facts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_text       TEXT NOT NULL,
    source_session  TEXT,
    created_at      INTEGER NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
    fact_text, content=facts, content_rowid=id
);

CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts(rowid, fact_text) VALUES (new.id, new.fact_text);
END;

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
"""


def _get_db() -> sqlite3.Connection:
    global _db
    if _db is not None:
        return _db
    _db = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    _db.execute("PRAGMA journal_mode=WAL")
    _db.execute("PRAGMA foreign_keys=ON")
    try:
        _db.execute("PRAGMA integrity_check")
        _db.executescript(_SCHEMA_SQL)
    except sqlite3.DatabaseError:
        _db.close()
        _db = None
        _rebuild_db()
        _db = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        _db.execute("PRAGMA journal_mode=WAL")
        _db.execute("PRAGMA foreign_keys=ON")
        _db.executescript(_SCHEMA_SQL)
    _db.commit()
    return _db


def _rebuild_db():
    db_path = Path(config.DB_PATH)
    if db_path.exists():
        backup = db_path.with_suffix(f".corrupt.{int(time.time())}.db")
        shutil.move(str(db_path), str(backup))
        logger.log_error("memory", "db_rebuild", "DatabaseCorrupt",
                         stderr=f"Backed up corrupt DB to {backup.name}")
    for suffix in ("-wal", "-shm"):
        wal = db_path.with_name(db_path.name + suffix)
        if wal.exists():
            wal.unlink()


def _reset_and_reconnect():
    global _db
    with _db_lock:
        if _db is not None:
            try:
                _db.close()
            except Exception:
                pass
            _db = None
        _rebuild_db()
        return _get_db()


# --- Session state (single user, single process) ---

_current_session_id: str | None = None
_session_start: int = 0
_session_base_tags: set[str] = set()


def _gen_session_id() -> str:
    now = datetime.now(_TZ)
    return f"sess_{now:%Y%m%d_%H%M}"


def _create_session() -> str:
    global _current_session_id, _session_start, _session_base_tags
    sid = _gen_session_id()
    now = int(time.time())
    with _db_lock:
        db = _get_db()
        db.execute(
            "INSERT OR REPLACE INTO sessions (session_id, start_time) VALUES (?, ?)",
            (sid, now),
        )
        db.commit()
    _current_session_id = sid
    _session_start = now
    _session_base_tags = set()
    return sid


def get_current_session_id() -> str:
    if _current_session_id is None:
        try:
            _recover_or_create()
        except sqlite3.DatabaseError:
            _reset_and_reconnect()
            _recover_or_create()
    return _current_session_id


def check_session_boundary() -> bool:
    global _current_session_id
    if _current_session_id is None:
        try:
            _recover_or_create()
        except sqlite3.DatabaseError:
            _reset_and_reconnect()
            _recover_or_create()
        return False

    now = int(time.time())
    if now - _session_start > _SESSION_TIMEOUT:
        try:
            _close_session(_current_session_id)
        except sqlite3.DatabaseError:
            _reset_and_reconnect()
        _create_session()
        return True
    return False


def _recover_or_create():
    with _db_lock:
        db = _get_db()
        row = db.execute(
            "SELECT session_id, start_time, base_tags FROM sessions "
            "WHERE end_time IS NULL ORDER BY start_time DESC LIMIT 1"
        ).fetchone()

    if row is None:
        _create_session()
        return

    global _current_session_id, _session_start, _session_base_tags
    sid, start, tags_json = row
    now = int(time.time())

    if now - start < _SESSION_TIMEOUT:
        _current_session_id = sid
        _session_start = start
        try:
            _session_base_tags = set(json.loads(tags_json)) if tags_json else set()
        except (json.JSONDecodeError, TypeError):
            _session_base_tags = set()
    else:
        try:
            _session_base_tags = set(json.loads(tags_json)) if tags_json else set()
        except (json.JSONDecodeError, TypeError):
            _session_base_tags = set()
        _close_session(sid)
        _create_session()


# --- Message persistence ---

def _serialize_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        blocks = []
        for item in content:
            if isinstance(item, dict):
                blocks.append(item)
            elif hasattr(item, "type"):
                block = {"type": item.type}
                if hasattr(item, "text"):
                    block["text"] = item.text
                if hasattr(item, "name"):
                    block["name"] = item.name
                if hasattr(item, "input"):
                    block["input"] = item.input
                if hasattr(item, "id"):
                    block["id"] = item.id
                blocks.append(block)
            else:
                blocks.append(str(item))
        return json.dumps(blocks, ensure_ascii=False)
    return json.dumps(content, ensure_ascii=False, default=str)


def persist_message(session_id: str, role: str, content: Any):
    serialized = _serialize_content(content)
    now = int(time.time())
    try:
        with _db_lock:
            db = _get_db()
            db.execute(
                "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (session_id, role, serialized, now),
            )
            db.execute(
                "UPDATE sessions SET message_count = message_count + 1 WHERE session_id = ?",
                (session_id,),
            )
            db.commit()
    except sqlite3.DatabaseError:
        _reset_and_reconnect()


def load_session_messages(session_id: str) -> list[dict]:
    try:
        with _db_lock:
            db = _get_db()
            rows = db.execute(
                "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
    except sqlite3.DatabaseError:
        _reset_and_reconnect()
        return []
    messages = []
    for role, content_str in rows:
        try:
            content = json.loads(content_str)
        except (json.JSONDecodeError, TypeError):
            content = content_str
        messages.append({"role": role, "content": content})
    return messages


# --- Base tag tracking ---

def track_tool_call(tool_name: str):
    tag = TOOL_TAG_MAP.get(tool_name)
    if tag:
        _session_base_tags.add(tag)


# --- Summarization ---

_SUMMARY_PROMPT = """请根据以下对话记录生成摘要、标签和事实。

## 对话记录
{history}

## 要求
输出严格的 JSON 格式（不要包含其他文字），结构如下：
{{
  "summary": "200字以内中文摘要，概括用户意图、关键操作和结果",
  "tags": {{
    "people": ["人名"],
    "topic": "主题关键词",
    "action": ["动作，优先用：查询/创建/修改/删除/分析/讨论/提醒/搜索"],
    "entity": ["实体名"],
    "extra": ["0-2个补充标签"]
  }},
  "facts": ["持久事实，如 '张三是产品经理'、'北极星项目预计6月上线'。没有则为空数组。"]
}}"""


def _compress_history(messages: list[dict]) -> str:
    parts = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "user":
            if isinstance(content, str):
                parts.append(f"用户: {content}")
            # tool_result lists — skip (drop raw tool output)
            continue

        if role == "assistant":
            if isinstance(content, str):
                if content:
                    parts.append(f"助手: {content}")
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text" and block.get("text"):
                            parts.append(f"助手: {block['text']}")
                        elif block.get("type") == "tool_use":
                            name = block.get("name", "?")
                            inp = block.get("input", {})
                            brief = ", ".join(
                                f"{k}={str(v)[:50]}" for k, v in list(inp.items())[:3]
                            )
                            parts.append(f"[调用工具 {name}({brief})]")
                    elif hasattr(block, "type"):
                        if block.type == "text" and hasattr(block, "text"):
                            parts.append(f"助手: {block.text}")
                        elif block.type == "tool_use":
                            name = getattr(block, "name", "?")
                            inp = getattr(block, "input", {})
                            brief = ", ".join(
                                f"{k}={str(v)[:50]}" for k, v in list(inp.items())[:3]
                            )
                            parts.append(f"[调用工具 {name}({brief})]")

            # OpenAI format: tool_calls is a separate key
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                for tc in tool_calls:
                    func = tc.get("function", {})
                    name = func.get("name", "?")
                    try:
                        args = json.loads(func.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        args = {}
                    brief = ", ".join(
                        f"{k}={str(v)[:50]}" for k, v in list(args.items())[:3]
                    )
                    parts.append(f"[调用工具 {name}({brief})]")
            continue

    return "\n".join(parts)


def _parse_llm_json(text: str) -> dict | None:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _close_session(session_id: str):
    messages = load_session_messages(session_id)
    now = int(time.time())
    base_tags_snapshot = set(_session_base_tags)

    if len(messages) < 4:
        with _db_lock:
            db = _get_db()
            db.execute(
                "UPDATE sessions SET end_time = ?, summary = ?, base_tags = ? WHERE session_id = ?",
                (now, "短对话", json.dumps(sorted(base_tags_snapshot), ensure_ascii=False), session_id),
            )
            db.commit()
        return

    compressed = _compress_history(messages)
    if not compressed.strip():
        with _db_lock:
            db = _get_db()
            db.execute(
                "UPDATE sessions SET end_time = ?, summary = ?, base_tags = ? WHERE session_id = ?",
                (now, "空对话", json.dumps(sorted(base_tags_snapshot), ensure_ascii=False), session_id),
            )
            db.commit()
        return

    threading.Thread(
        target=_run_summarization,
        args=(compressed, session_id, now, base_tags_snapshot),
        daemon=True,
    ).start()


_summary_client = None


def _get_summary_client():
    global _summary_client
    if _summary_client is not None:
        return _summary_client
    model = config.LLM_SUMMARY_MODEL
    is_anthropic_model = model.startswith("claude")
    if config.LLM_PROVIDER == "anthropic" and not is_anthropic_model:
        _summary_client = llm.OpenAIClient.__new__(llm.OpenAIClient)
        from openai import OpenAI
        import httpx as _httpx
        kwargs: dict = {
            "api_key": config.ANTHROPIC_API_KEY,
            "timeout": _httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0),
        }
        if config.ANTHROPIC_BASE_URL:
            base = config.ANTHROPIC_BASE_URL.rstrip("/")
            if not base.endswith("/v1"):
                base += "/v1"
            kwargs["base_url"] = base
        _summary_client._client = OpenAI(**kwargs)
    else:
        _summary_client = llm.get_client()
    return _summary_client


def _run_summarization(compressed: str, session_id: str, now: int, base_tags: set[str]):
    base_tags_json = json.dumps(sorted(base_tags), ensure_ascii=False)

    try:
        client = _get_summary_client()
        prompt = _SUMMARY_PROMPT.format(history=compressed)
        response = client.chat(
            messages=[{"role": "user", "content": prompt}],
            system="你是一个对话摘要助手。严格按 JSON 格式输出，不要输出其他文字。",
            tools=[],
            model=config.LLM_SUMMARY_MODEL,
            max_tokens=1024,
        )
        parsed = _parse_llm_json(response.text or "")
    except Exception as e:
        logger.log_error("memory", "summarization", type(e).__name__, stderr=str(e))
        try:
            with _db_lock:
                db = _get_db()
                db.execute(
                    "UPDATE sessions SET end_time = ?, summary = ?, base_tags = ? WHERE session_id = ?",
                    (now, "[摘要生成失败]", base_tags_json, session_id),
                )
                db.commit()
        except sqlite3.DatabaseError:
            pass
        return

    if not parsed:
        try:
            with _db_lock:
                db = _get_db()
                db.execute(
                    "UPDATE sessions SET end_time = ?, summary = ?, base_tags = ? WHERE session_id = ?",
                    (now, compressed[:200], base_tags_json, session_id),
                )
                db.commit()
        except sqlite3.DatabaseError:
            pass
        return

    summary = parsed.get("summary", "")[:500]
    tags = parsed.get("tags", {})
    people = ", ".join(tags.get("people", [])) if isinstance(tags.get("people"), list) else str(tags.get("people", ""))
    topic = str(tags.get("topic", ""))
    action = ", ".join(tags.get("action", [])) if isinstance(tags.get("action"), list) else str(tags.get("action", ""))
    entity = ", ".join(tags.get("entity", [])) if isinstance(tags.get("entity"), list) else str(tags.get("entity", ""))
    extra = ", ".join(tags.get("extra", [])) if isinstance(tags.get("extra"), list) else str(tags.get("extra", ""))

    try:
        with _db_lock:
            db = _get_db()
            db.execute(
                "UPDATE sessions SET end_time=?, summary=?, base_tags=?, people=?, topic=?, action=?, entity=?, extra_tags=? "
                "WHERE session_id=?",
                (now, summary, base_tags_json, people, topic, action, entity, extra, session_id),
            )

            facts = parsed.get("facts", [])
            for fact in facts:
                if isinstance(fact, str) and fact.strip():
                    db.execute(
                        "INSERT INTO facts (fact_text, source_session, created_at) VALUES (?, ?, ?)",
                        (fact.strip(), session_id, now),
                    )

            db.commit()
    except sqlite3.DatabaseError:
        pass


# --- recall_memory tool ---

_TIME_RANGE_MAP = {
    "1d": 86400,
    "3d": 259200,
    "7d": 604800,
    "30d": 2592000,
}


def _escape_fts(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def recall_memory(inputs: dict) -> str:
    try:
        session_id = inputs.get("session_id")
        if session_id:
            return _recall_expand(session_id)
        return _recall_search(inputs)
    except sqlite3.DatabaseError:
        _reset_and_reconnect()
        return "记忆数据库已重建，历史记忆已丢失。请重试。"


def _recall_expand(session_id: str) -> str:
    with _db_lock:
        db = _get_db()
        row = db.execute(
            "SELECT summary, base_tags, people, topic, action, entity, extra_tags, start_time, end_time "
            "FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()

    if not row:
        return f"未找到 session: {session_id}"

    summary, base_tags, people, topic, action, entity, extra, start, end = row
    messages = load_session_messages(session_id)

    header = f"Session: {session_id}\n"
    header += f"时间: {_fmt_time(start)} ~ {_fmt_time(end)}\n"
    if summary:
        header += f"摘要: {summary}\n"
    tags_parts = []
    if base_tags:
        tags_parts.append(base_tags)
    if people:
        tags_parts.append(f"人物: {people}")
    if topic:
        tags_parts.append(f"主题: {topic}")
    if header:
        header += f"标签: {' | '.join(tags_parts)}\n"
    header += "\n--- 对话记录 ---\n"

    parts = [header]
    total_len = len(header)
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user" and isinstance(content, str):
            line = f"用户: {content}\n"
        elif role == "assistant":
            if isinstance(content, str):
                line = f"助手: {content}\n"
            else:
                line = f"助手: {_serialize_content(content)[:300]}\n"
        else:
            continue
        total_len += len(line)
        if total_len > 4000:
            parts.append("... (对话过长，已截断)")
            break
        parts.append(line)

    return "".join(parts)


def _recall_search(inputs: dict) -> str:
    now = int(time.time())

    time_range = inputs.get("time_range", "all")
    min_time = 0
    if time_range in _TIME_RANGE_MAP:
        min_time = now - _TIME_RANGE_MAP[time_range]

    # Build FTS5 query
    fts_terms = []
    for field in ("topic", "people", "action", "entity"):
        val = inputs.get(field)
        if val:
            fts_terms.append(f"{field}: {_escape_fts(val)}")
    keyword = inputs.get("keyword")
    if keyword:
        fts_terms.append(_escape_fts(keyword))

    results_parts = []

    with _db_lock:
        db = _get_db()

        if fts_terms:
            fts_query = " OR ".join(fts_terms)
            rows = db.execute(
                "SELECT s.session_id, s.start_time, s.end_time, s.summary, "
                "s.base_tags, s.people, s.topic, s.action, s.entity, s.extra_tags, rank "
                "FROM sessions_fts f JOIN sessions s ON f.rowid = s.rowid "
                "WHERE sessions_fts MATCH ? AND s.start_time >= ? AND s.end_time IS NOT NULL "
                "ORDER BY rank LIMIT 5",
                (fts_query, min_time),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT session_id, start_time, end_time, summary, "
                "base_tags, people, topic, action, entity, extra_tags, 0 "
                "FROM sessions WHERE end_time IS NOT NULL AND start_time >= ? "
                "ORDER BY start_time DESC LIMIT 5",
                (min_time,),
            ).fetchall()

    if rows:
        results_parts.append(f"## 相关历史 Session (共 {len(rows)} 条)\n")
        for i, row in enumerate(rows, 1):
            sid, start, end, summary, base_tags, people, topic, action, entity, extra, _ = row
            results_parts.append(
                f"{i}. [{sid}] {_fmt_time(start)} ~ {_fmt_time(end)}\n"
                f"   摘要: {summary or '(无)'}\n"
            )
            tag_parts = []
            if base_tags:
                tag_parts.append(base_tags)
            if people:
                tag_parts.append(f"人物: {people}")
            if topic:
                tag_parts.append(f"主题: {topic}")
            if tag_parts:
                results_parts.append(f"   标签: {' | '.join(tag_parts)}\n")
            results_parts.append(f"   → 调用 recall_memory(session_id=\"{sid}\") 查看完整对话\n\n")

    # Search facts
    if keyword or any(inputs.get(f) for f in ("topic", "people", "entity")):
        fact_terms = []
        for val in [keyword, inputs.get("topic"), inputs.get("people"), inputs.get("entity")]:
            if val:
                fact_terms.append(_escape_fts(val))
        fact_query = " OR ".join(fact_terms)
        with _db_lock:
            db = _get_db()
            fact_rows = db.execute(
                "SELECT f2.fact_text, f2.source_session, f2.created_at "
                "FROM facts_fts f JOIN facts f2 ON f.rowid = f2.id "
                "WHERE facts_fts MATCH ? ORDER BY rank LIMIT 5",
                (fact_query,),
            ).fetchall()

        if fact_rows:
            results_parts.append(f"## 相关事实 (共 {len(fact_rows)} 条)\n")
            for fact_text, src, created in fact_rows:
                results_parts.append(f"- {fact_text} (来源: {src}, {_fmt_time(created)})\n")

    if not results_parts:
        return "未找到相关历史记忆。"

    return "".join(results_parts)


def _fmt_time(ts: int | None) -> str:
    if not ts:
        return "?"
    return datetime.fromtimestamp(ts, _TZ).strftime("%Y-%m-%d %H:%M")


# --- Register tool ---

register(ToolDef(
    name="recall_memory",
    description="搜索历史对话记忆",
    identity="",
    category="research",
    claude_schema=_schema(
        "recall_memory",
        "搜索历史对话记忆。当用户提到过去的对话、之前做过的事、或需要历史上下文时调用。"
        "可以按主题、人名、动作、实体、关键词和时间范围搜索。"
        "也可以传 session_id 展开某个 session 的完整对话记录。",
        {
            "session_id": {
                "type": "string",
                "description": "展开某个 session 的完整对话记录。传了则忽略其他参数。",
            },
            "topic": {"type": "string", "description": "主题关键词"},
            "people": {"type": "string", "description": "相关人名"},
            "action": {"type": "string", "description": "动作类型"},
            "entity": {"type": "string", "description": "实体名称"},
            "keyword": {"type": "string", "description": "全文搜索关键词"},
            "time_range": {
                "type": "string",
                "enum": ["1d", "3d", "7d", "30d", "all"],
                "description": "时间范围，默认 all",
            },
        },
    ),
    python_func=recall_memory,
))
