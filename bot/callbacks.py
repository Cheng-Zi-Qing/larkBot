"""bot/callbacks.py — 构建 agent 回调闭包。"""
from __future__ import annotations

import time

from bot.transport import send_reply
from bot import formatter


def make_progress_cb(chat_id: str):
    """构建 on_progress 回调。格式化委托给 formatter。"""
    last_ts = 0.0

    def _on_progress(tool_names: list[str], tool_inputs: list[dict],
                     tool_outputs: list[str], tool_successes: list[bool],
                     step: int, total: int, plan_steps: list[str] | None):
        nonlocal last_ts
        now = time.time()
        if now - last_ts < 1.0:
            return
        last_ts = now
        text = formatter.format_progress(
            tool_names, tool_inputs, tool_outputs, tool_successes,
            step, total, plan_steps,
        )
        send_reply(chat_id, text)

    return _on_progress


def make_plan_cb(chat_id: str):
    """构建 on_plan 回调。"""
    def _on_plan(steps: list[str]):
        send_reply(chat_id, formatter.format_plan(steps))
    return _on_plan
