"""bot/commands.py — 斜杠命令处理。"""
from __future__ import annotations

from dataclasses import dataclass

import config
import hooks
from bot.transport import send_reply


@dataclass
class ForwardEvent:
    """commands 需要 router 转发的消息"""
    chat_id: str
    content: str
    sender_id: str = ""


_ASSIS_MAP = {
    "/assis-a": "analyst",
    "/assis-p": "pm",
    "/assis-o": "ops",
    "/assis-r": "reviewer",
    "/assis": "assistant",
}


def handle(content: str, chat_id: str, request_id: str) -> ForwardEvent | None:
    """
    处理斜杠命令。返回 ForwardEvent 时 router 需要转发消息。
    返回 None 表示命令已处理完毕。
    """
    cmd = content.strip().lower()

    # /assis* aliases: map to persona key and optionally forward remaining text
    for prefix, persona_key in _ASSIS_MAP.items():
        if cmd == prefix or cmd.startswith(prefix + " "):
            name = config.set_persona(persona_key)
            remainder = content.strip()[len(prefix):].strip()
            if remainder:
                send_reply(chat_id, f"已切换为: {name}")
                return ForwardEvent(chat_id=chat_id, content=remainder)
            else:
                send_reply(chat_id, f"已切换为: {name}")
                return None

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

    return None
