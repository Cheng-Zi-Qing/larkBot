"""bot/transport.py — 消息传输层：发送回复 + 消息去重。"""
from __future__ import annotations

import subprocess
import sys
import threading
import time

_seen_messages: dict[str, float] = {}
_seen_lock = threading.Lock()

_DEDUP_WINDOW = 60.0  # seconds


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


def dedup_check(message_id: str) -> bool:
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
