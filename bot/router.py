"""bot/router.py — 消息路由：意图分类、任务管理、agent 调用。"""
from __future__ import annotations

import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import agent
import config
import logger
from bot.transport import send_reply, dedup_check
from bot import commands, callbacks

_INTENT_PROMPT = (
    "你是一个意图分类器。用户之前发了一条消息启动了任务，现在又发了新消息。\n"
    "请判断新消息的意图，只输出一个词：\n"
    "- cancel — 用户想取消/撤回/重来/换个问法\n"
    "- supplement — 用户在补充信息/纠正细节/追加要求（原始任务目标不变）\n"
    "- confirm — 用户在确认执行（如：好的、执行、确认、可以）\n"
    "- status — 用户在打招呼/问在不在/闲聊/不需要任何操作（如：你在么、你是谁、在吗）\n"
    "- new_task — 用户发了一个全新的、与旧任务无关的指令\n\n"
    "旧任务: {old_message}\n"
    "新消息: {new_message}\n\n"
    "只输出 cancel/supplement/confirm/status/new_task 中的一个词。"
)


@dataclass
class _ChatTask:
    """Tracks a running agent task for a chat."""
    cancel_event: threading.Event
    original_message: str
    request_id: str


_active_tasks: dict[str, _ChatTask] = {}  # chat_id → running task
_tasks_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=4)


def classify_intent(old_message: str, new_message: str) -> str:
    """LLM call to classify new message intent relative to running task."""
    try:
        import llm
        client = llm.get_client()
        prompt = _INTENT_PROMPT.format(old_message=old_message[:200], new_message=new_message[:200])
        resp = client.chat(
            messages=[{"role": "user", "content": prompt}],
            system="只输出一个分类词，不要输出其他内容。",
            tools=[],
            model=config.LLM_MODEL,
            max_tokens=10,
        )
        result = (resp.text or "").strip().lower()
        if result in ("cancel", "supplement", "confirm", "status", "new_task"):
            return result
        # Fuzzy match
        for word in ("cancel", "supplement", "confirm", "status", "new_task"):
            if word in result:
                return word
        return "new_task"
    except Exception:
        return "new_task"


def handle_message(event: dict):
    """主路由逻辑：去重 → 命令 → 意图分类 → 分派 agent。"""
    chat_id = event.get("chat_id", "")
    sender_id = event.get("sender_id", "")
    content = event.get("content", "")
    message_id = event.get("message_id", "")
    event_id = event.get("event_id", "")
    request_id = f"req_{uuid.uuid4().hex[:12]}"

    if not content:
        return

    # Deduplicate: use event_id first, fallback to message_id
    dedup_key = event_id or message_id
    if dedup_check(dedup_key):
        print(f"[BOT] [{request_id}] Dedup skip: {dedup_key}", file=sys.stderr)
        return

    # Command handling
    if content.startswith("/"):
        forward = commands.handle(content, chat_id, request_id)
        if forward:
            handle_message({"chat_id": forward.chat_id, "sender_id": forward.sender_id,
                            "content": forward.content, "message_id": ""})
        return

    # Check if there's a running task for this chat
    with _tasks_lock:
        active = _active_tasks.get(chat_id)

    if active and not active.cancel_event.is_set():
        # There's a running task — classify intent
        intent = classify_intent(active.original_message, content)
        print(f"[BOT] [{request_id}] Intent: {intent} (old: {active.original_message[:40]})", file=sys.stderr)

        if intent == "confirm":
            _run_task(request_id, chat_id, sender_id, content, message_id, clear_history=False)
            return

        elif intent == "status":
            send_reply(chat_id, f"🔄 正在执行中: {active.original_message[:50]}\n请稍候，完成后会通知你。")
            return

        elif intent == "cancel":
            active.cancel_event.set()
            send_reply(chat_id, f"⏹️ 已取消: {active.original_message[:50]}")
            return

        elif intent == "supplement":
            active.cancel_event.set()
            merged = f"{active.original_message}\n\n[补充] {content}"
            send_reply(chat_id, f"📝 收到补充，重新执行:\n原始: {active.original_message[:50]}\n补充: {content[:50]}")
            _run_task(request_id, chat_id, sender_id, merged, message_id)
            return

        elif intent == "new_task":
            active.cancel_event.set()
            send_reply(chat_id, f"⏹️ 已取消旧任务: {active.original_message[:50]}\n▶️ 开始新任务")
            _run_task(request_id, chat_id, sender_id, content, message_id)
            return

    # No active task — check if resuming after plan confirmation
    has_pending_plan = bool(agent.history.get(chat_id))
    _run_task(request_id, chat_id, sender_id, content, message_id, clear_history=not has_pending_plan)


def _run_task(request_id: str, chat_id: str, sender_id: str, content: str, message_id: str,
              clear_history: bool = True):
    """Start a new agent task in the thread pool."""
    cancel_event = threading.Event()
    task = _ChatTask(cancel_event=cancel_event, original_message=content, request_id=request_id)

    with _tasks_lock:
        old = _active_tasks.get(chat_id)
        if old:
            old.cancel_event.set()
        _active_tasks[chat_id] = task

    # Only clear history when starting a genuinely new task
    if clear_history:
        agent.history.pop(chat_id, None)
        with agent._plans_lock:
            agent._confirmed_plans.pop(chat_id, None)

    def _execute():
        try:
            _process_message(request_id, chat_id, sender_id, content, message_id, cancel_event)
        finally:
            with _tasks_lock:
                # Only clear if this is still the active task
                if _active_tasks.get(chat_id) is task:
                    del _active_tasks[chat_id]

    _executor.submit(_execute)


def _process_message(
    request_id: str, chat_id: str, sender_id: str, content: str, message_id: str,
    cancel_event: threading.Event | None = None,
):
    print(f"[BOT] [{request_id}] From {sender_id}: {content[:80]}", file=sys.stderr)

    try:
        reply = agent.run(request_id, chat_id, content, sender_id=sender_id,
                          on_progress=callbacks.make_progress_cb(chat_id),
                          on_plan=callbacks.make_plan_cb(chat_id),
                          cancel_event=cancel_event)

        # If cancelled mid-run, don't send reply — new task owns the chat now
        if cancel_event and cancel_event.is_set():
            print(f"[BOT] [{request_id}] Cancelled, discarding result", file=sys.stderr)
            return

        if not reply or not reply.strip():
            reply = "（模型返回为空，请重新描述你的问题）"

        # Routing suggestion: hint user if another persona is better suited
        suggested = config.detect_persona_routing(content)
        if suggested:
            persona_name = config.PERSONAS.get(suggested, {}).get("name", suggested)
            reply += f"\n\n💡 这类问题切换到 /{suggested}（{persona_name}）可能效果更好"

        send_reply(chat_id, reply)
    except Exception as e:
        # If cancelled, swallow errors silently
        if cancel_event and cancel_event.is_set():
            print(f"[BOT] [{request_id}] Cancelled (exception swallowed): {e}", file=sys.stderr)
            return
        logger.log_error(request_id, "bot", "AgentError", stderr=str(e))
        err_name = type(e).__name__
        err_detail = str(e)[:200]
        if "rate" in err_name.lower():
            send_reply(chat_id, "当前请求太频繁，请稍等片刻再试。")
        elif "timeout" in err_name.lower():
            send_reply(chat_id, "请求超时了，请稍后再试。")
        elif "content-blocked" in err_detail or "content_blocked" in err_detail:
            send_reply(chat_id, "请求被上游服务拦截，请稍后重试。如持续出现请联系管理员。")
        else:
            send_reply(chat_id, f"处理失败（{err_name}）：{err_detail}")


def shutdown():
    """关闭线程池。"""
    _executor.shutdown(wait=False)
