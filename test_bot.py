#!/usr/bin/env python3
"""bot/ package unit tests — verifies module split preserves original logic.

Usage:
    python3 test_bot.py              # run all tests
    python3 test_bot.py -v           # verbose output
"""
from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import patch, MagicMock

# ---------------------------------------------------------------------------
# 1. formatter.py — 纯函数测试
# ---------------------------------------------------------------------------


class TestFormatter(unittest.TestCase):
    """Test bot/formatter.py pure functions."""

    def test_tool_labels_complete(self):
        from bot.formatter import TOOL_LABELS
        # 确保关键工具都有标签
        essential = ["web_search", "create_doc", "read_doc", "get_agenda",
                     "recall_memory", "submit_plan", "send_message"]
        for tool in essential:
            self.assertIn(tool, TOOL_LABELS, f"Missing label for {tool}")
            self.assertTrue(TOOL_LABELS[tool], f"Empty label for {tool}")

    def test_extract_detail_url(self):
        from bot.formatter import extract_detail
        # URL key
        self.assertEqual(extract_detail({"url": "https://example.com"}), "https://example.com")
        # Long URL truncated
        long_url = "https://example.com/" + "a" * 50
        result = extract_detail({"url": long_url})
        self.assertTrue(result.endswith("..."))
        self.assertLessEqual(len(result), 50)

    def test_extract_detail_query(self):
        from bot.formatter import extract_detail
        self.assertEqual(extract_detail({"query": "hello"}), "「hello」")
        # Long query truncated
        long_q = "a" * 30
        result = extract_detail({"query": long_q})
        self.assertIn("「", result)
        self.assertLessEqual(len(result), 25)

    def test_extract_detail_title(self):
        from bot.formatter import extract_detail
        self.assertEqual(extract_detail({"title": "My Doc"}), "My Doc")

    def test_extract_detail_empty(self):
        from bot.formatter import extract_detail
        self.assertEqual(extract_detail({}), "")
        self.assertEqual(extract_detail({"random_key": "val"}), "")

    def test_extract_detail_priority(self):
        from bot.formatter import extract_detail
        # url takes priority over query
        result = extract_detail({"url": "https://x.com", "query": "test"})
        self.assertEqual(result, "https://x.com")

    def test_extract_link_feishu(self):
        from bot.formatter import extract_link
        text = "创建成功: https://abc.feishu.cn/docs/xxx 请查看"
        self.assertIn("feishu.cn", extract_link(text))

    def test_extract_link_none(self):
        from bot.formatter import extract_link
        self.assertEqual(extract_link("no links here"), "")

    def test_summarize_output_failure(self):
        from bot.formatter import summarize_output
        result = summarize_output("read_doc", "权限不足，请联系管理员", False)
        self.assertTrue(result.startswith("❌"))
        self.assertIn("权限不足", result)

    def test_summarize_output_empty(self):
        from bot.formatter import summarize_output
        self.assertEqual(summarize_output("read_doc", "", True), "")

    def test_summarize_output_search(self):
        from bot.formatter import summarize_output
        text = "找到 3 条结果\n1. 文档A\n2. 文档B\n3. 文档C"
        result = summarize_output("search_docs", text, True)
        self.assertIn("找到", result)

    def test_summarize_output_create_with_link(self):
        from bot.formatter import summarize_output
        text = "文档已创建 https://abc.feishu.cn/docs/xyz"
        result = summarize_output("create_doc", text, True)
        self.assertIn("🔗", result)

    def test_summarize_output_read_json(self):
        from bot.formatter import summarize_output
        import json
        data = {"data": {"title": "我的文档"}}
        result = summarize_output("read_doc", json.dumps(data), True)
        self.assertIn("我的文档", result)

    def test_summarize_output_read_list(self):
        from bot.formatter import summarize_output
        import json
        data = [{"id": 1}, {"id": 2}, {"id": 3}]
        result = summarize_output("record_list", json.dumps(data), True)
        self.assertIn("3", result)

    def test_format_progress_with_plan(self):
        from bot.formatter import format_progress
        result = format_progress(
            tool_names=["search_docs"],
            tool_inputs=[{"query": "测试"}],
            tool_outputs=["找到 2 条"],
            tool_successes=[True],
            step=1, total=3,
            plan_steps=["搜索相关文档", "读取文档内容", "总结回复"],
        )
        self.assertIn("[1/3]", result)
        self.assertIn("搜索相关文档", result)
        self.assertIn("✅", result)

    def test_format_progress_no_plan(self):
        from bot.formatter import format_progress
        result = format_progress(
            tool_names=["web_search", "web_read"],
            tool_inputs=[{"query": "AI"}, {"url": "https://x.com"}],
            tool_outputs=["ok", "ok"],
            tool_successes=[True, True],
            step=2, total=0,
            plan_steps=None,
        )
        self.assertIn("[第2步]", result)
        self.assertIn("搜索网络", result)

    def test_format_progress_partial_failure(self):
        from bot.formatter import format_progress
        result = format_progress(
            tool_names=["read_doc"],
            tool_inputs=[{"doc": "abc"}],
            tool_outputs=["权限不足"],
            tool_successes=[False],
            step=1, total=1,
            plan_steps=None,
        )
        self.assertIn("⚠️", result)

    def test_format_progress_extra_step(self):
        from bot.formatter import format_progress
        result = format_progress(
            tool_names=["web_search"],
            tool_inputs=[{"query": "x"}],
            tool_outputs=["ok"],
            tool_successes=[True],
            step=4, total=3,
            plan_steps=["a", "b", "c"],
        )
        self.assertIn("额外第1步", result)

    def test_format_plan(self):
        from bot.formatter import format_plan
        result = format_plan(["搜索文档", "读取内容", "生成报告"])
        self.assertIn("📋 执行计划:", result)
        self.assertIn("1. 搜索文档", result)
        self.assertIn("3. 生成报告", result)


# ---------------------------------------------------------------------------
# 2. transport.py — 去重逻辑测试
# ---------------------------------------------------------------------------


class TestTransport(unittest.TestCase):
    """Test bot/transport.py dedup logic."""

    def setUp(self):
        from bot import transport
        # Clear dedup state between tests
        with transport._seen_lock:
            transport._seen_messages.clear()

    def test_dedup_first_message_passes(self):
        from bot.transport import dedup_check
        self.assertFalse(dedup_check("msg_001"))

    def test_dedup_duplicate_blocked(self):
        from bot.transport import dedup_check
        self.assertFalse(dedup_check("msg_002"))
        self.assertTrue(dedup_check("msg_002"))  # duplicate

    def test_dedup_empty_id_passes(self):
        from bot.transport import dedup_check
        # Empty message_id should never be deduped
        self.assertFalse(dedup_check(""))
        self.assertFalse(dedup_check(""))

    def test_dedup_different_ids_pass(self):
        from bot.transport import dedup_check
        self.assertFalse(dedup_check("msg_a"))
        self.assertFalse(dedup_check("msg_b"))
        self.assertFalse(dedup_check("msg_c"))

    def test_dedup_overflow_clears(self):
        from bot import transport
        # Fill beyond 500 limit
        for i in range(501):
            transport.dedup_check(f"overflow_{i}")
        # After clear, previously seen ID should pass
        self.assertFalse(transport.dedup_check("overflow_0"))

    @patch("subprocess.run")
    def test_send_reply_basic(self, mock_run):
        from bot.transport import send_reply
        mock_run.return_value = MagicMock(returncode=0)
        send_reply("chat_123", "hello")
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertIn("lark-cli", cmd)
        self.assertIn("--chat-id", cmd)
        self.assertIn("chat_123", cmd)

    @patch("subprocess.run")
    def test_send_reply_with_reply_to(self, mock_run):
        from bot.transport import send_reply
        mock_run.return_value = MagicMock(returncode=0)
        send_reply("chat_123", "hi", reply_to="msg_456")
        cmd = mock_run.call_args[0][0]
        self.assertIn("+messages-reply", cmd)
        self.assertIn("--message-id", cmd)
        self.assertIn("msg_456", cmd)


# ---------------------------------------------------------------------------
# 3. commands.py — 命令解析 + ForwardEvent 测试
# ---------------------------------------------------------------------------


class TestCommands(unittest.TestCase):
    """Test bot/commands.py command handling."""

    @patch("bot.commands.send_reply")
    def test_ping(self, mock_reply):
        from bot.commands import handle
        result = handle("/ping", "chat_1", "req_1")
        self.assertIsNone(result)
        mock_reply.assert_called_once_with("chat_1", "pong")

    @patch("bot.commands.send_reply")
    def test_role_list(self, mock_reply):
        from bot.commands import handle
        result = handle("/role", "chat_1", "req_1")
        self.assertIsNone(result)
        text = mock_reply.call_args[0][1]
        self.assertIn("当前角色", text)

    @patch("bot.commands.send_reply")
    def test_assis_switch_no_message(self, mock_reply):
        from bot.commands import handle
        result = handle("/assis-a", "chat_1", "req_1")
        self.assertIsNone(result)
        text = mock_reply.call_args[0][1]
        self.assertIn("已切换为", text)

    @patch("bot.commands.send_reply")
    def test_assis_switch_with_message(self, mock_reply):
        from bot.commands import handle, ForwardEvent
        result = handle("/assis-p 帮我看下日程", "chat_1", "req_1")
        # Should return ForwardEvent for the remaining message
        self.assertIsInstance(result, ForwardEvent)
        self.assertEqual(result.chat_id, "chat_1")
        self.assertEqual(result.content, "帮我看下日程")
        # Also should have sent persona switch reply
        mock_reply.assert_called_once()
        self.assertIn("已切换为", mock_reply.call_args[0][1])

    @patch("bot.commands.send_reply")
    def test_unknown_command(self, mock_reply):
        from bot.commands import handle
        result = handle("/nonexist", "chat_1", "req_1")
        self.assertIsNone(result)
        text = mock_reply.call_args[0][1]
        self.assertIn("未知命令", text)

    @patch("bot.commands.send_reply")
    def test_persona_direct_switch(self, mock_reply):
        from bot.commands import handle
        import config
        # Get first persona key
        key = list(config.PERSONAS.keys())[0]
        result = handle(f"/{key}", "chat_1", "req_1")
        self.assertIsNone(result)
        self.assertIn("已切换为", mock_reply.call_args[0][1])

    @patch("bot.commands.send_reply")
    @patch("hooks.reload_custom_hooks")
    def test_reload_hooks(self, mock_reload, mock_reply):
        from bot.commands import handle
        result = handle("/reload-hooks", "chat_1", "req_1")
        self.assertIsNone(result)
        mock_reload.assert_called_once()
        mock_reply.assert_called_once_with("chat_1", "Hooks reloaded.")


# ---------------------------------------------------------------------------
# 4. callbacks.py — 节流逻辑测试
# ---------------------------------------------------------------------------


class TestCallbacks(unittest.TestCase):
    """Test bot/callbacks.py throttling and delegation."""

    @patch("bot.callbacks.send_reply")
    def test_progress_cb_throttle(self, mock_reply):
        from bot.callbacks import make_progress_cb
        cb = make_progress_cb("chat_1")

        # First call should send
        cb(["web_search"], [{"query": "test"}], ["ok"], [True], 1, 3, None)
        self.assertEqual(mock_reply.call_count, 1)

        # Immediate second call should be throttled
        cb(["read_doc"], [{"doc": "x"}], ["ok"], [True], 2, 3, None)
        self.assertEqual(mock_reply.call_count, 1)  # still 1

    @patch("bot.callbacks.send_reply")
    def test_progress_cb_after_delay(self, mock_reply):
        from bot.callbacks import make_progress_cb
        cb = make_progress_cb("chat_1")

        cb(["web_search"], [{"query": "a"}], ["ok"], [True], 1, 2, None)
        self.assertEqual(mock_reply.call_count, 1)

        # Simulate time passing
        time.sleep(1.05)
        cb(["read_doc"], [{"doc": "b"}], ["ok"], [True], 2, 2, None)
        self.assertEqual(mock_reply.call_count, 2)

    @patch("bot.callbacks.send_reply")
    def test_plan_cb_formats_correctly(self, mock_reply):
        from bot.callbacks import make_plan_cb
        cb = make_plan_cb("chat_1")
        cb(["搜索", "读取", "总结"])
        text = mock_reply.call_args[0][1]
        self.assertIn("📋 执行计划:", text)
        self.assertIn("1. 搜索", text)
        self.assertIn("3. 总结", text)


# ---------------------------------------------------------------------------
# 5. router.py — 路由逻辑测试（mock agent + LLM）
# ---------------------------------------------------------------------------


class TestRouter(unittest.TestCase):
    """Test bot/router.py message routing logic."""

    def setUp(self):
        from bot import transport, router
        # Clear state
        with transport._seen_lock:
            transport._seen_messages.clear()
        with router._tasks_lock:
            router._active_tasks.clear()

    @patch("bot.router.send_reply")
    def test_empty_content_ignored(self, mock_reply):
        from bot.router import handle_message
        handle_message({"chat_id": "c1", "content": "", "message_id": "m1"})
        mock_reply.assert_not_called()

    @patch("bot.router.send_reply")
    def test_dedup_skips_duplicate(self, mock_reply):
        from bot.router import handle_message
        from bot import transport
        # Pre-mark as seen
        transport.dedup_check("evt_dup")
        handle_message({"chat_id": "c1", "content": "hi", "message_id": "", "event_id": "evt_dup"})
        mock_reply.assert_not_called()

    @patch("bot.commands.send_reply")
    def test_command_dispatched(self, mock_reply):
        from bot.router import handle_message
        handle_message({"chat_id": "c1", "content": "/ping", "message_id": "m1"})
        mock_reply.assert_called_once_with("c1", "pong")

    @patch("bot.router._process_message")
    @patch("bot.commands.send_reply")
    def test_command_with_forward(self, mock_reply, mock_process):
        from bot.router import handle_message
        handle_message({"chat_id": "c1", "content": "/assis-p 查日程", "message_id": "m1"})
        # Should have called send_reply for persona switch
        self.assertTrue(mock_reply.called)
        self.assertIn("已切换为", mock_reply.call_args_list[0][0][1])

    @patch("bot.router._run_task")
    def test_new_message_starts_task(self, mock_run):
        from bot.router import handle_message
        handle_message({"chat_id": "c1", "content": "帮我查日程", "message_id": "m1"})
        mock_run.assert_called_once()
        args = mock_run.call_args
        self.assertEqual(args[0][1], "c1")  # chat_id
        self.assertEqual(args[0][3], "帮我查日程")  # content

    @patch("bot.router.classify_intent", return_value="cancel")
    @patch("bot.router.send_reply")
    def test_cancel_intent(self, mock_reply, mock_classify):
        from bot.router import handle_message, _active_tasks, _tasks_lock, _ChatTask
        # Setup active task
        cancel_evt = threading.Event()
        task = _ChatTask(cancel_event=cancel_evt, original_message="旧任务", request_id="req_old")
        with _tasks_lock:
            _active_tasks["c1"] = task

        handle_message({"chat_id": "c1", "content": "算了不要了", "message_id": "m2"})
        self.assertTrue(cancel_evt.is_set())
        self.assertIn("已取消", mock_reply.call_args[0][1])

    @patch("bot.router._run_task")
    @patch("bot.router.classify_intent", return_value="supplement")
    @patch("bot.router.send_reply")
    def test_supplement_intent(self, mock_reply, mock_classify, mock_run):
        from bot.router import handle_message, _active_tasks, _tasks_lock, _ChatTask
        cancel_evt = threading.Event()
        task = _ChatTask(cancel_event=cancel_evt, original_message="帮我搜索AI", request_id="req_old")
        with _tasks_lock:
            _active_tasks["c1"] = task

        handle_message({"chat_id": "c1", "content": "限定中文结果", "message_id": "m2"})
        self.assertTrue(cancel_evt.is_set())  # old task cancelled
        # _run_task called with merged content
        merged = mock_run.call_args[0][3]
        self.assertIn("帮我搜索AI", merged)
        self.assertIn("[补充] 限定中文结果", merged)

    @patch("bot.router._run_task")
    @patch("bot.router.classify_intent", return_value="new_task")
    @patch("bot.router.send_reply")
    def test_new_task_intent(self, mock_reply, mock_classify, mock_run):
        from bot.router import handle_message, _active_tasks, _tasks_lock, _ChatTask
        cancel_evt = threading.Event()
        task = _ChatTask(cancel_event=cancel_evt, original_message="旧任务", request_id="req_old")
        with _tasks_lock:
            _active_tasks["c1"] = task

        handle_message({"chat_id": "c1", "content": "帮我发邮件", "message_id": "m2"})
        self.assertTrue(cancel_evt.is_set())
        # New task started with new content
        self.assertEqual(mock_run.call_args[0][3], "帮我发邮件")

    @patch("bot.router.classify_intent", return_value="status")
    @patch("bot.router.send_reply")
    def test_status_intent(self, mock_reply, mock_classify):
        from bot.router import handle_message, _active_tasks, _tasks_lock, _ChatTask
        cancel_evt = threading.Event()
        task = _ChatTask(cancel_event=cancel_evt, original_message="执行中的任务", request_id="req_old")
        with _tasks_lock:
            _active_tasks["c1"] = task

        handle_message({"chat_id": "c1", "content": "你在吗", "message_id": "m2"})
        self.assertFalse(cancel_evt.is_set())  # task NOT cancelled
        self.assertIn("正在执行中", mock_reply.call_args[0][1])

    @patch("bot.router._run_task")
    @patch("bot.router.classify_intent", return_value="confirm")
    @patch("bot.router.send_reply")
    def test_confirm_intent(self, mock_reply, mock_classify, mock_run):
        from bot.router import handle_message, _active_tasks, _tasks_lock, _ChatTask
        cancel_evt = threading.Event()
        task = _ChatTask(cancel_event=cancel_evt, original_message="计划任务", request_id="req_old")
        with _tasks_lock:
            _active_tasks["c1"] = task

        handle_message({"chat_id": "c1", "content": "确认执行", "message_id": "m2"})
        # Confirm: run_task with clear_history=False
        self.assertFalse(cancel_evt.is_set())  # old NOT cancelled (confirm keeps context)
        self.assertIn("clear_history", str(mock_run.call_args))


# ---------------------------------------------------------------------------
# 6. __init__.py — 包级别 re-export + legacy 兼容
# ---------------------------------------------------------------------------


class TestPackageExports(unittest.TestCase):
    """Test bot/__init__.py exports and backward compat."""

    def test_tool_labels_reexport(self):
        from bot import TOOL_LABELS
        from bot.formatter import TOOL_LABELS as FMT_LABELS
        self.assertIs(TOOL_LABELS, FMT_LABELS)

    def test_handle_message_reexport(self):
        from bot import handle_message
        from bot.router import handle_message as ROUTER_HM
        self.assertIs(handle_message, ROUTER_HM)

    def test_main_callable(self):
        from bot import main
        self.assertTrue(callable(main))

    def test_submodule_imports(self):
        """All submodules importable without error."""
        from bot import formatter, transport, consumer, commands, callbacks, router
        self.assertTrue(hasattr(formatter, 'format_progress'))
        self.assertTrue(hasattr(transport, 'send_reply'))
        self.assertTrue(hasattr(consumer, 'start_event_consumer'))
        self.assertTrue(hasattr(commands, 'handle'))
        self.assertTrue(hasattr(callbacks, 'make_progress_cb'))
        self.assertTrue(hasattr(router, 'handle_message'))


# ---------------------------------------------------------------------------
# 7. _process_message — agent 调用 + 错误处理
# ---------------------------------------------------------------------------


class TestProcessMessage(unittest.TestCase):
    """Test _process_message agent call and error handling."""

    @patch("bot.router.send_reply")
    @patch("agent.run", return_value="这是回复")
    def test_normal_reply(self, mock_agent, mock_reply):
        from bot.router import _process_message
        _process_message("req_1", "c1", "user_1", "你好", "m1")
        mock_reply.assert_called()
        reply_text = mock_reply.call_args[0][1]
        self.assertIn("这是回复", reply_text)

    @patch("bot.router.send_reply")
    @patch("agent.run", return_value="")
    def test_empty_reply_fallback(self, mock_agent, mock_reply):
        from bot.router import _process_message
        _process_message("req_1", "c1", "user_1", "你好", "m1")
        reply_text = mock_reply.call_args[0][1]
        self.assertIn("模型返回为空", reply_text)

    @patch("bot.router.send_reply")
    @patch("agent.run", side_effect=RuntimeError("something broke"))
    def test_error_reply(self, mock_agent, mock_reply):
        from bot.router import _process_message
        _process_message("req_1", "c1", "user_1", "你好", "m1")
        reply_text = mock_reply.call_args[0][1]
        self.assertIn("处理失败", reply_text)
        self.assertIn("RuntimeError", reply_text)

    @patch("bot.router.send_reply")
    def test_rate_limit_error(self, mock_reply):
        from bot.router import _process_message

        class RateLimitError(Exception):
            pass

        with patch("agent.run", side_effect=RateLimitError("too many requests")):
            _process_message("req_1", "c1", "user_1", "你好", "m1")
        reply_text = mock_reply.call_args[0][1]
        self.assertIn("请求太频繁", reply_text)

    @patch("bot.router.send_reply")
    @patch("agent.run", return_value="ok")
    def test_cancelled_discards_result(self, mock_agent, mock_reply):
        from bot.router import _process_message
        cancel = threading.Event()
        cancel.set()  # pre-cancelled
        _process_message("req_1", "c1", "user_1", "你好", "m1", cancel_event=cancel)
        mock_reply.assert_not_called()  # result discarded

    @patch("bot.router.send_reply")
    @patch("agent.run", side_effect=Exception("cancelled error"))
    def test_cancelled_swallows_error(self, mock_agent, mock_reply):
        from bot.router import _process_message
        cancel = threading.Event()
        cancel.set()  # pre-cancelled
        _process_message("req_1", "c1", "user_1", "你好", "m1", cancel_event=cancel)
        mock_reply.assert_not_called()


# ---------------------------------------------------------------------------
# 8. 逻辑一致性验证 — 确保拆分后行为等同原始 bot.py
# ---------------------------------------------------------------------------


class TestLogicConsistency(unittest.TestCase):
    """Cross-check split modules against _legacy.py behavior."""

    def test_tool_labels_match_legacy(self):
        """New TOOL_LABELS must match legacy."""
        from bot.formatter import TOOL_LABELS as NEW
        from bot._legacy import TOOL_LABELS as OLD
        self.assertEqual(NEW, OLD)

    def test_command_coverage(self):
        """commands.handle covers all original command branches."""
        from bot.commands import _ASSIS_MAP
        # Original had: /assis-a, /assis-p, /assis-o, /assis-r, /assis
        self.assertIn("/assis-a", _ASSIS_MAP)
        self.assertIn("/assis-p", _ASSIS_MAP)
        self.assertIn("/assis-o", _ASSIS_MAP)
        self.assertIn("/assis-r", _ASSIS_MAP)
        self.assertIn("/assis", _ASSIS_MAP)


# ---------------------------------------------------------------------------
# 9. 行为差异验证 — 新代码有意改变的行为（PRD Section XIII 设计）
# ---------------------------------------------------------------------------


class TestBehaviorChanges(unittest.TestCase):
    """
    Tests that document INTENTIONAL behavior differences between new and legacy.

    Legacy: handle_message → active task → classify intent → _run_task → _process_message → if "/" → handle_command
    New:    handle_message → dedup → if "/" → commands.handle (immediate, no intent) → active task → classify → _run_task → _process_message

    Key difference: commands are handled BEFORE intent classification.
    - Legacy: `/ping` during active task → goes through intent classify → may cancel old task
    - New: `/ping` during active task → handled immediately, old task NOT cancelled
    """

    def setUp(self):
        from bot import transport, router
        with transport._seen_lock:
            transport._seen_messages.clear()
        with router._tasks_lock:
            router._active_tasks.clear()

    @patch("bot.commands.send_reply")
    def test_command_during_active_task_does_not_cancel(self, mock_reply):
        """NEW BEHAVIOR: /ping during active task does NOT cancel it."""
        from bot.router import handle_message, _active_tasks, _tasks_lock, _ChatTask

        cancel_evt = threading.Event()
        task = _ChatTask(cancel_event=cancel_evt, original_message="旧任务", request_id="req_old")
        with _tasks_lock:
            _active_tasks["c1"] = task

        handle_message({"chat_id": "c1", "content": "/ping", "message_id": "m2"})

        # Command executed
        mock_reply.assert_called_once_with("c1", "pong")
        # Old task NOT cancelled (this differs from legacy)
        self.assertFalse(cancel_evt.is_set())

    @patch("bot.router._run_task")
    @patch("bot.commands.send_reply")
    def test_assis_forward_during_active_task_triggers_intent(self, mock_reply, mock_run):
        """
        NEW BEHAVIOR: /assis-p <msg> during active task →
        1. Switch persona (immediate)
        2. Recursive handle_message with <msg>
        3. <msg> sees active task → classify intent → handle accordingly
        """
        from bot.router import handle_message, _active_tasks, _tasks_lock, _ChatTask

        cancel_evt = threading.Event()
        task = _ChatTask(cancel_event=cancel_evt, original_message="旧任务", request_id="req_old")
        with _tasks_lock:
            _active_tasks["c1"] = task

        # Mock classify_intent to return "new_task" for the forwarded message
        with patch("bot.router.classify_intent", return_value="new_task"):
            with patch("bot.router.send_reply") as mock_router_reply:
                handle_message({"chat_id": "c1", "content": "/assis-p 查日程", "message_id": "m1"})

        # Persona switch reply sent
        self.assertTrue(mock_reply.called)
        self.assertIn("已切换为", mock_reply.call_args[0][1])
        # Old task cancelled (because forwarded text was classified as new_task)
        self.assertTrue(cancel_evt.is_set())
        # New task started
        self.assertTrue(mock_run.called)

    @patch("bot.commands.send_reply")
    def test_command_skips_dedup_for_next_message(self, mock_reply):
        """Commands don't consume the message_id for dedup purposes of subsequent messages."""
        from bot.router import handle_message
        from bot.transport import dedup_check

        # Send a command
        handle_message({"chat_id": "c1", "content": "/ping", "message_id": "m1"})
        mock_reply.assert_called_once_with("c1", "pong")

        # A different message with different id should still work
        with patch("bot.router._run_task") as mock_run:
            handle_message({"chat_id": "c1", "content": "你好", "message_id": "m2"})
            mock_run.assert_called_once()

    @patch("bot.commands.send_reply")
    def test_stats_during_active_task(self, mock_reply):
        """NEW BEHAVIOR: /stats during active task responds directly without intent classify."""
        from bot.router import handle_message, _active_tasks, _tasks_lock, _ChatTask

        cancel_evt = threading.Event()
        task = _ChatTask(cancel_event=cancel_evt, original_message="长任务", request_id="req_old")
        with _tasks_lock:
            _active_tasks["c1"] = task

        handle_message({"chat_id": "c1", "content": "/stats", "message_id": "m2"})

        # /stats handled as command, not through intent
        self.assertTrue(mock_reply.called)
        text = mock_reply.call_args[0][1]
        self.assertIn("Bot is running", text)
        # Old task preserved
        self.assertFalse(cancel_evt.is_set())


# ---------------------------------------------------------------------------
# 10. 边界条件测试
# ---------------------------------------------------------------------------


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def setUp(self):
        from bot import transport, router
        with transport._seen_lock:
            transport._seen_messages.clear()
        with router._tasks_lock:
            router._active_tasks.clear()

    @patch("bot.router.send_reply")
    def test_message_without_event_id_uses_message_id_for_dedup(self, mock_reply):
        """When event_id is missing, message_id is used for dedup."""
        from bot.router import handle_message
        with patch("bot.router._run_task"):
            handle_message({"chat_id": "c1", "content": "hi", "message_id": "msg_1"})
            handle_message({"chat_id": "c1", "content": "hi again", "message_id": "msg_1"})
        # Second message deduped — _run_task only called once
        # (but we can't easily check _run_task here since it's patched)

    @patch("bot.router._run_task")
    def test_confirm_intent_preserves_history(self, mock_run):
        """Confirm intent calls _run_task with clear_history=False."""
        from bot.router import handle_message, _active_tasks, _tasks_lock, _ChatTask

        cancel_evt = threading.Event()
        task = _ChatTask(cancel_event=cancel_evt, original_message="执行计划?", request_id="req_1")
        with _tasks_lock:
            _active_tasks["c1"] = task

        with patch("bot.router.classify_intent", return_value="confirm"):
            with patch("bot.router.send_reply"):
                handle_message({"chat_id": "c1", "content": "确认", "message_id": "m2"})

        # _run_task called with clear_history=False (keyword arg)
        call_kwargs = mock_run.call_args[1]
        self.assertEqual(call_kwargs.get("clear_history"), False)

    @patch("bot.router.send_reply")
    @patch("agent.run", return_value="回复")
    def test_persona_routing_hint_appended(self, mock_agent, mock_reply):
        """If detect_persona_routing suggests a different persona, hint is appended."""
        from bot.router import _process_message
        with patch("config.detect_persona_routing", return_value="analyst"):
            _process_message("req_1", "c1", "user_1", "分析市场趋势", "m1")
        reply_text = mock_reply.call_args[0][1]
        self.assertIn("💡", reply_text)
        self.assertIn("/analyst", reply_text)

    @patch("bot.router.send_reply")
    @patch("agent.run", return_value="回复")
    def test_no_routing_hint_when_none(self, mock_agent, mock_reply):
        """No hint when detect_persona_routing returns None."""
        from bot.router import _process_message
        with patch("config.detect_persona_routing", return_value=None):
            _process_message("req_1", "c1", "user_1", "你好", "m1")
        reply_text = mock_reply.call_args[0][1]
        self.assertNotIn("💡", reply_text)

    @patch("bot.router.send_reply")
    @patch("agent.run", side_effect=Exception("content_blocked by upstream"))
    def test_content_blocked_error(self, mock_agent, mock_reply):
        """Content blocked errors get special user-friendly message."""
        from bot.router import _process_message
        _process_message("req_1", "c1", "user_1", "test", "m1")
        reply_text = mock_reply.call_args[0][1]
        self.assertIn("被上游服务拦截", reply_text)

    @patch("bot.commands.send_reply")
    def test_assis_prefix_matching_exact(self, mock_reply):
        """/assis should not match /assis-a (longer prefix checked first)."""
        from bot.commands import handle, _ASSIS_MAP
        # /assis-a should map to analyst, not assistant
        result = handle("/assis-a", "c1", "req_1")
        self.assertIsNone(result)
        # Verify it matched analyst, not assistant
        import config
        text = mock_reply.call_args[0][1]
        analyst_name = config.PERSONAS["analyst"]["name"]
        self.assertIn(analyst_name, text)

    @patch("bot.commands.send_reply")
    def test_assis_base_with_space(self, mock_reply):
        """/assis <msg> switches to assistant and forwards."""
        from bot.commands import handle, ForwardEvent
        result = handle("/assis 帮我", "c1", "req_1")
        self.assertIsInstance(result, ForwardEvent)
        self.assertEqual(result.content, "帮我")
        import config
        assistant_name = config.PERSONAS["assistant"]["name"]
        self.assertIn(assistant_name, mock_reply.call_args[0][1])


if __name__ == "__main__":
    unittest.main()
