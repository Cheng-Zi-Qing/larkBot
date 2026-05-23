#!/usr/bin/env python3
"""Local agent integration test — runs agent.run() directly without Feishu.

Usage:
    python3 test_agent.py                    # run all test cases
    python3 test_agent.py "自定义消息"        # run a single custom message
    python3 test_agent.py --case 2           # run specific case by index
    python3 test_agent.py --dry              # only test workflow matching, no LLM call
"""
from __future__ import annotations

import sys
import time

import config
config.validate()

import agent
import workflows

# ---------------------------------------------------------------------------
# Test cases — cover all personas and workflow types
# ---------------------------------------------------------------------------

TEST_CASES = [
    # (persona, message, expected_workflow, description)
    ("assistant", "今天有什么安排", "daily_briefing", "每日早报（assistant 基本功能）"),
    ("assistant", "帮我整理今天的会议纪要", "meeting_digest", "会议纪要（assistant + 多工具）"),
    ("analyst", "帮我分析一下 AI Agent 市场", "market_analysis", "市场分析（analyst 深度调研）"),
    ("pm", "帮我做一份竞品分析，对比 Notion AI 和 Cursor", "competitive_analysis", "竞品分析（pm 多步）"),
    ("pm", "帮我写一份 PRD，做一个内部知识库搜索工具", "prd", "PRD 生成（pm 复杂任务）"),
    ("ops", "帮我做一个内容策划方案，主题是 AI 编程工具", "content_plan", "内容策划（ops）"),
    ("ops", "我们产品刚上线，帮我设计一个冷启动获客方案", "growth_plan", "增长方案（ops）"),
    ("assistant", "你好", None, "简单问答（无工作流匹配）"),
    ("analyst", "帮我查一下最近 AI 领域有哪些融资", None, "模糊匹配测试"),
]


# ---------------------------------------------------------------------------
# Callbacks — print to console
# ---------------------------------------------------------------------------

def on_progress(tool_names, tool_inputs, step, total, plan_steps, thought=""):
    prefix = f"[{step}/{total}]" if total > 0 else f"[第{step}步]"
    tools_str = ", ".join(tool_names)
    print(f"  📎 {prefix} {tools_str}")
    if thought:
        t = thought.strip().replace("\n", " ")
        if len(t) > 100:
            t = t[:97] + "..."
        print(f"  💭 {t}")


def on_plan(steps):
    print(f"  📋 执行计划 ({len(steps)} 步):")
    for i, s in enumerate(steps, 1):
        print(f"     {i}. {s}")


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def test_workflow_match_only():
    """Dry run: only test workflow matching logic, no LLM calls."""
    print("=" * 60)
    print("  DRY RUN — 仅测试工作流匹配（不调用 LLM）")
    print("=" * 60)

    passed = 0
    failed = 0
    for i, (persona, msg, expected_wf, desc) in enumerate(TEST_CASES, 1):
        config.set_persona(persona)
        wf = workflows.match(msg, persona)
        wf_id = wf.id if wf else None
        ok = wf_id == expected_wf
        status = "✓" if ok else "✗"
        print(f"  {status} [{i}] [{persona}] {desc}")
        if not ok:
            print(f"       期望: {expected_wf}, 实际: {wf_id}")
            failed += 1
        else:
            passed += 1

    # Test routing detection
    print(f"\n  路由检测:")
    routing_tests = [
        ("帮我做市场规模测算", "analyst"),
        ("写个竞品分析", "pm"),
        ("设计一个获客方案", "ops"),
        ("今天天气怎么样", None),
    ]
    for msg, expected in routing_tests:
        config.set_persona("assistant")
        result = config.detect_persona_routing(msg)
        ok = result == expected
        status = "✓" if ok else "✗"
        print(f"  {status} \"{msg}\" → {result} (期望: {expected})")
        if ok:
            passed += 1
        else:
            failed += 1

    print(f"\n  结果: {passed} 通过, {failed} 失败")
    return failed == 0


def run_single_case(persona: str, message: str, desc: str):
    """Run a single test case with full agent loop."""
    config.set_persona(persona)
    wf = workflows.match(message, persona)

    print(f"\n{'─' * 60}")
    print(f"  角色: {persona} ({config.PERSONAS[persona]['name']})")
    print(f"  消息: {message}")
    print(f"  工作流: {wf.name if wf else '(无匹配)'}")
    print(f"  描述: {desc}")
    print(f"{'─' * 60}")

    chat_id = f"test_{int(time.time())}"
    request_id = f"test_req_{int(time.time())}"

    start = time.monotonic()
    try:
        reply = agent.run(
            request_id=request_id,
            chat_id=chat_id,
            user_message=message,
            sender_id="test_user",
            on_progress=on_progress,
            on_plan=on_plan,
        )
        elapsed = time.monotonic() - start

        print(f"\n  ✅ 完成 ({elapsed:.1f}s)")
        print(f"  {'─' * 40}")
        # Truncate long replies for readability
        if len(reply) > 2000:
            print(f"  {reply[:2000]}")
            print(f"  ... ({len(reply)} 字符，已截断)")
        else:
            print(f"  {reply}")
        return True

    except Exception as e:
        elapsed = time.monotonic() - start
        print(f"\n  ❌ 失败 ({elapsed:.1f}s): {type(e).__name__}: {e}")
        return False


def main():
    args = sys.argv[1:]

    # --dry: only test matching
    if "--dry" in args:
        success = test_workflow_match_only()
        sys.exit(0 if success else 1)

    # --case N: run specific case
    if "--case" in args:
        idx = int(args[args.index("--case") + 1]) - 1
        if 0 <= idx < len(TEST_CASES):
            persona, msg, _, desc = TEST_CASES[idx]
            run_single_case(persona, msg, desc)
        else:
            print(f"Case index out of range (1-{len(TEST_CASES)})")
            sys.exit(1)
        return

    # Custom message
    if args and not args[0].startswith("--"):
        message = " ".join(args)
        persona = config.get_persona()
        run_single_case(persona, message, "自定义消息")
        return

    # Run all cases
    print("=" * 60)
    print("  larkBot Agent 集成测试")
    print(f"  LLM: {config.LLM_PROVIDER} / {config.LLM_MODEL}")
    print("=" * 60)

    # First do dry run
    test_workflow_match_only()
    print()

    # Then ask which cases to run with LLM
    print("\n可用测试用例:")
    for i, (persona, msg, wf, desc) in enumerate(TEST_CASES, 1):
        print(f"  {i}. [{persona}] {desc}")
        print(f"     \"{msg}\"")

    print(f"\n输入用例编号运行 (1-{len(TEST_CASES)})，或 'all' 全部运行，'q' 退出:")
    while True:
        try:
            choice = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        if choice in ("q", "quit", "exit"):
            break
        elif choice == "all":
            for persona, msg, _, desc in TEST_CASES:
                run_single_case(persona, msg, desc)
                print()
            break
        else:
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(TEST_CASES):
                    persona, msg, _, desc = TEST_CASES[idx]
                    run_single_case(persona, msg, desc)
                else:
                    print(f"  范围: 1-{len(TEST_CASES)}")
            except ValueError:
                # Treat as custom message
                run_single_case(config.get_persona(), choice, "自定义消息")


if __name__ == "__main__":
    main()
