from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum


class PlanDecision(Enum):
    PAUSE_FOR_CONFIRM = "pause"
    AUTO_CONFIRM = "auto"


# Per-chat persisted plan state — survives across agent loops (plan confirm + HITL pause)
_persisted_plans: dict[str, dict] = {}
_plans_lock = threading.Lock()

# Backward compat alias (used by bot.py)
_confirmed_plans = _persisted_plans


_WRITE_KEYWORDS = (
    "创建", "写入", "新建", "生成", "输出文档", "落文档", "发送", "回复",
    "编辑", "修改", "更新", "追加", "覆写", "删除", "移动",
    "create", "write", "send", "edit", "delete", "update", "append",
)

_CONFIRM_KEYWORDS = ("执行", "确认", "好的", "可以", "继续", "没问题", "ok", "yes", "go")

_CONFIRM_REQUEST_MARKERS = (
    "⚠️ 即将执行",
    "确认后我将继续执行",
    "以上计划包含写入操作",
    "确认后开始执行",
)


@dataclass
class PlanState:
    steps: list[str] = field(default_factory=list)
    confirmed: bool = False
    has_write_steps: bool = False
    step_counter: int = 0
    total_steps: int = 0

    def is_confirmed(self) -> bool:
        return self.confirmed

    def advance(self) -> None:
        self.step_counter += 1

    def submit(self, steps: list[str], messages: list[dict]) -> PlanDecision:
        """
        Submit a new plan, return decision:
        - PAUSE_FOR_CONFIRM: has write steps, needs user confirmation
        - AUTO_CONFIRM: pure read or user pre-confirmed, proceed directly
        """
        self.steps = steps
        self.total_steps = len(steps)
        self.has_write_steps = _plan_has_write_steps(steps)

        if not self.has_write_steps or _user_pre_confirmed(messages):
            self.confirmed = True
            return PlanDecision.AUTO_CONFIRM
        else:
            return PlanDecision.PAUSE_FOR_CONFIRM

    def confirm(self) -> None:
        """Mark plan as confirmed (after user confirms)."""
        self.confirmed = True

    def restore(self, chat_id: str) -> bool:
        """Restore plan state from persistent storage (after plan confirm or HITL pause)."""
        with _plans_lock:
            saved = _persisted_plans.pop(chat_id, None)
        if not saved:
            return False
        if isinstance(saved, list):
            # Legacy format: just steps list
            self.steps = saved
            self.total_steps = len(saved)
            self.confirmed = True
        else:
            # Full state dict
            self.steps = saved.get("steps", [])
            self.total_steps = saved.get("total_steps", len(self.steps))
            self.step_counter = saved.get("step_counter", 0)
            self.confirmed = saved.get("confirmed", True)
        return True

    def persist(self, chat_id: str) -> None:
        """Save full plan state so next loop can restore it."""
        with _plans_lock:
            _persisted_plans[chat_id] = {
                "steps": self.steps,
                "total_steps": self.total_steps,
                "step_counter": self.step_counter,
                "confirmed": self.confirmed,
            }

    def persist_for_confirm(self, chat_id: str) -> None:
        """Save plan so next loop can restore it after user confirms."""
        self.persist(chat_id)


def clear_persisted_plan(chat_id: str) -> None:
    """Clear persisted plan for a chat (used when starting fresh task)."""
    with _plans_lock:
        _confirmed_plans.pop(chat_id, None)


def _plan_has_write_steps(plan_steps: list[str]) -> bool:
    """Check if any plan step involves write/create/delete operations."""
    for step in plan_steps:
        step_lower = step.lower()
        if any(kw in step_lower for kw in _WRITE_KEYWORDS):
            return True
    return False


def _user_pre_confirmed(messages: list[dict]) -> bool:
    """
    Check if the user confirmed a high-risk action or plan in recent messages.
    Only returns True when:
    1. A recent assistant message contains a confirm-request marker (HITL or Plan)
    2. A subsequent user message contains a confirm keyword
    This prevents false positives from casual phrases like "好的，帮我查日程".
    """
    # Find most recent assistant confirm-request marker (look back up to 6 messages)
    marker_idx = None
    start = max(len(messages) - 6, 0)
    for i in range(len(messages) - 1, start - 1, -1):
        msg = messages[i]
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", "")
        if isinstance(content, str) and any(m in content for m in _CONFIRM_REQUEST_MARKERS):
            marker_idx = i
            break

    if marker_idx is None:
        return False

    # Check if any user message after the marker contains a confirm keyword
    for msg in messages[marker_idx + 1:]:
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            text = content.strip().lower()
            if any(kw in text for kw in _CONFIRM_KEYWORDS):
                return True
    return False
