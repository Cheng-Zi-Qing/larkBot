"""bot/consumer.py — lark-cli event consumer 进程管理。"""
from __future__ import annotations

import subprocess
import sys
import threading
import time


def start_event_consumer() -> subprocess.Popen:
    """启动 lark-cli event consume。"""
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


def shutdown_consumer(proc: subprocess.Popen) -> None:
    """优雅关闭 consumer 进程。"""
    proc.stdin.close()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
