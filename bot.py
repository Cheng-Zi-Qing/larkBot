from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import uuid

import agent
import config
import hooks
import logger
import web_tools  # noqa: F401 — registers web tools
import memory  # noqa: F401 — registers recall_memory tool
from hooks import HookContext


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

    print(f"[BOT] [{request_id}] From {sender_id}: {content[:80]}", file=sys.stderr)

    if content.startswith("/"):
        handle_command(content, chat_id, request_id)
        return

    try:
        reply = agent.run(request_id, chat_id, content)
        send_reply(chat_id, reply, message_id)
    except Exception as e:
        logger.log_error(request_id, "bot", "AgentError", stderr=str(e))
        send_reply(chat_id, f"处理失败，请稍后再试。({type(e).__name__})")


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
                handle_message(event)
            except json.JSONDecodeError:
                logger.log_error("system", "bot", "json_parse", stderr=f"Bad line: {line[:200]}")
    except KeyboardInterrupt:
        print("\n[BOT] Shutting down...", file=sys.stderr)
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
