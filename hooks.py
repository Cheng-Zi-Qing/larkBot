from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import config

HOOK_POINTS = [
    "on_message_in",
    "before_agent",
    "before_tool",
    "after_tool",
    "on_error",
    "on_reply",
]

HIGH_RISK_TOOLS = {"create_doc", "write_table", "create_event", "create_task", "send_message"}


@dataclass
class HookContext:
    request_id: str = ""
    chat_id: str = ""
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    messages: list[dict] = field(default_factory=list)
    reply_text: str = ""
    exit_code: int | None = None
    stderr: str = ""
    stdout: str = ""
    duration_ms: float = 0
    retry_count: int = 0
    extra_flags: list[str] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)

    def with_error(self, error_type: str) -> HookContext:
        ctx = HookContext(
            request_id=self.request_id, chat_id=self.chat_id,
            tool_name=self.tool_name, tool_input=self.tool_input,
            messages=self.messages, reply_text=self.reply_text,
            exit_code=self.exit_code, stderr=self.stderr, stdout=self.stdout,
            duration_ms=self.duration_ms, retry_count=self.retry_count,
            extra_flags=list(self.extra_flags), extras=dict(self.extras),
        )
        ctx.extras["error_type"] = error_type
        return ctx

    def with_result(self, proc, duration_ms: float) -> HookContext:
        ctx = HookContext(
            request_id=self.request_id, chat_id=self.chat_id,
            tool_name=self.tool_name, tool_input=self.tool_input,
            messages=self.messages, reply_text=self.reply_text,
            retry_count=self.retry_count,
            extra_flags=list(self.extra_flags), extras=dict(self.extras),
        )
        ctx.exit_code = proc.returncode
        ctx.stderr = proc.stderr or ""
        ctx.stdout = proc.stdout or ""
        ctx.duration_ms = duration_ms
        return ctx


@dataclass
class HookResult:
    skip: bool = False
    retry: bool = False
    override_output: str = ""
    user_notify: str = ""


_registry: dict[str, list[tuple[int, str, Callable]]] = {p: [] for p in HOOK_POINTS}


def hook(point: str, priority: int = 10):
    def decorator(fn: Callable[[HookContext], HookResult]):
        if point not in _registry:
            raise ValueError(f"Unknown hook point: {point}")
        _registry[point].append((priority, fn.__name__, fn))
        _registry[point].sort(key=lambda t: t[0])
        return fn
    return decorator


def fire(point: str, ctx: HookContext) -> HookResult:
    merged = HookResult()
    for _prio, _name, fn in _registry.get(point, []):
        try:
            result = fn(ctx)
            if result.skip:
                merged.skip = True
            if result.retry:
                merged.retry = True
            if result.override_output:
                merged.override_output = result.override_output
            if result.user_notify:
                merged.user_notify = result.user_notify
        except Exception as e:
            print(f"[HOOK] Error in {_name}@{point}: {e}", file=sys.stderr)
    return merged


def load_custom_hooks(directory: Path | None = None):
    directory = directory or config.HOOKS_CUSTOM_DIR
    if not directory.is_dir():
        return
    for py_file in sorted(directory.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        module_name = f"hooks_custom.{py_file.stem}"
        spec = importlib.util.spec_from_file_location(module_name, py_file)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = mod
            try:
                spec.loader.exec_module(mod)
                print(f"[HOOK] Loaded custom hook: {py_file.name}", file=sys.stderr)
            except Exception as e:
                print(f"[HOOK] Failed to load {py_file.name}: {e}", file=sys.stderr)


def reload_custom_hooks():
    for point in _registry:
        _registry[point] = [
            (p, n, fn) for p, n, fn in _registry[point]
            if not n.startswith("custom_")
        ]
    load_custom_hooks()


# --- Built-in hooks ---

@hook("on_error", priority=0)
def builtin_permission_error(ctx: HookContext) -> HookResult:
    if ctx.exit_code == 1 and "scope" in ctx.stderr:
        return HookResult(
            user_notify=f"需要额外权限: {ctx.stderr[:200]}"
        )
    return HookResult()


@hook("before_tool", priority=5)
def builtin_high_risk_guard(ctx: HookContext) -> HookResult:
    return HookResult()
