from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import config

TZ = timezone(timedelta(hours=8))


def _ts() -> str:
    return datetime.now(TZ).isoformat(timespec="milliseconds")


def _today() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d")


def _log_path(name: str) -> Path:
    return config.LOG_DIR / f"{name}.{_today()}.jsonl"


def _append(path: Path, record: dict):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def log_tool_call(
    request_id: str,
    tool_name: str,
    tool_input: dict,
    cmd: list[str],
    proc,
    duration_ms: float,
):
    _append(
        _log_path("tool_calls"),
        {
            "ts": _ts(),
            "request_id": request_id,
            "tool": tool_name,
            "input": tool_input,
            "lark_cli_cmd": cmd,
            "exit_code": proc.returncode,
            "output_size": len(proc.stdout) if proc.stdout else 0,
            "output_preview": (proc.stdout or "")[:300],
            "duration_ms": round(duration_ms, 1),
            "success": proc.returncode == 0,
            "error": proc.stderr[:500] if proc.returncode != 0 and proc.stderr else None,
        },
    )


def log_error(
    request_id: str,
    source: str,
    error_type: str,
    *,
    stderr: str = "",
    exit_code: int | None = None,
    duration_ms: float | None = None,
    suggestion: str = "",
    retry_attempted: bool = False,
):
    _append(
        _log_path("errors"),
        {
            "ts": _ts(),
            "request_id": request_id,
            "level": "ERROR",
            "source": f"tool:{source}" if ":" not in source else source,
            "error_type": error_type,
            "exit_code": exit_code,
            "lark_cli_stderr": stderr[:500] if stderr else None,
            "suggestion": suggestion or None,
            "retry_attempted": retry_attempted,
            "duration_ms": round(duration_ms, 1) if duration_ms is not None else None,
        },
    )


def log_conversation(
    request_id: str,
    chat_id: str,
    user_message: str,
    messages: list[dict],
    reply_text: str,
):
    _append(
        _log_path("conversations"),
        {
            "ts": _ts(),
            "request_id": request_id,
            "chat_id": chat_id,
            "user_message": user_message,
            "reply": reply_text,
            "rounds": len([m for m in messages if m.get("role") == "assistant"]),
            "tool_calls": len(
                [
                    m
                    for m in messages
                    if m.get("role") == "user"
                    and isinstance(m.get("content"), list)
                    and any(
                        isinstance(c, dict) and c.get("type") == "tool_result"
                        for c in m["content"]
                    )
                ]
            ),
        },
    )
