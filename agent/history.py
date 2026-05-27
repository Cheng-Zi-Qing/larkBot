from __future__ import annotations

import threading
from collections import defaultdict

import config
import memory

history: dict[str, list[dict]] = defaultdict(list)
_history_lock = threading.Lock()


def trim(chat_id: str):
    msgs = history[chat_id]
    if len(msgs) > config.MAX_HISTORY * 2:
        history[chat_id] = msgs[-(config.MAX_HISTORY * 2):]


def sanitize_messages(messages: list[dict]) -> list[dict]:
    """Strip tool_use/tool_result blocks from restored history.

    Serialized SDK objects rarely round-trip cleanly, and an orphaned
    tool_use without its matching tool_result causes a 400 from the API.
    Keeping only text blocks is safe — the LLM loses tool context from
    prior turns but can still continue the conversation.
    """
    clean: list[dict] = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "assistant" and isinstance(content, list):
            text_blocks = [
                b for b in content
                if isinstance(b, dict) and b.get("type") == "text" and b.get("text")
            ]
            if text_blocks:
                clean.append({"role": "assistant", "content": text_blocks})
            elif any(isinstance(b, dict) and b.get("type") == "text" for b in content):
                pass
            else:
                continue

        elif role == "user" and isinstance(content, list):
            has_tool_result = any(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in content
            )
            if has_tool_result:
                continue
            clean.append(msg)

        elif role in ("user", "assistant"):
            clean.append(msg)

    return clean


def load_or_restore(chat_id: str, session_id: str, rotated: bool) -> list[dict]:
    """Load conversation history, handling session rotation."""
    with _history_lock:
        if rotated:
            history[chat_id] = []
        if not history.get(chat_id):
            history[chat_id] = sanitize_messages(memory.load_session_messages(session_id))
        return list(history.get(chat_id, []))


def save(chat_id: str, messages: list[dict]):
    """Persist messages and trim history."""
    with _history_lock:
        history[chat_id] = messages
        trim(chat_id)


def clear(chat_id: str):
    """Clear history for a chat (used on BadRequest retry)."""
    with _history_lock:
        history[chat_id] = []
