#!/usr/bin/env python3
"""Test LLM connectivity — reads .env config and sends a simple request."""

import sys
import time

import config
config.validate()

import llm


def main():
    provider = config.LLM_PROVIDER
    model = config.LLM_MODEL
    base_url = config.ANTHROPIC_BASE_URL if provider == "anthropic" else config.OPENAI_BASE_URL

    print(f"Provider:  {provider}")
    print(f"Model:     {model}")
    if base_url:
        print(f"Base URL:  {base_url}")
    print()

    # Test 1: simple chat
    print("[1/2] 测试基础对话...", end=" ", flush=True)
    start = time.monotonic()
    try:
        client = llm.get_client()
        resp = client.chat(
            messages=[{"role": "user", "content": "回复 OK 两个字"}],
            system="你是一个测试助手",
            tools=[],
            model=model,
        )
        elapsed = (time.monotonic() - start) * 1000
        print(f"✓ ({elapsed:.0f}ms)")
        print(f"   回复: {resp.text}")
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        print(f"✗ ({elapsed:.0f}ms)")
        print(f"   错误: {e}")
        sys.exit(1)

    # Test 2: tool_use
    print("\n[2/2] 测试 tool_use...", end=" ", flush=True)
    test_tool = {
        "name": "get_time",
        "description": "Get current time",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    }
    start = time.monotonic()
    try:
        resp = client.chat(
            messages=[{"role": "user", "content": "现在几点？请调用 get_time 工具"}],
            system="你是一个测试助手，请使用提供的工具回答问题",
            tools=[test_tool],
            model=model,
        )
        elapsed = (time.monotonic() - start) * 1000
        if resp.stop_reason == "tool_use" and resp.tool_calls:
            tc = resp.tool_calls[0]
            print(f"✓ ({elapsed:.0f}ms)")
            print(f"   工具调用: {tc.name}({tc.input})")
        else:
            print(f"⚠ ({elapsed:.0f}ms)")
            print(f"   模型未调用工具 (stop_reason={resp.stop_reason})")
            print(f"   回复: {resp.text}")
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        print(f"✗ ({elapsed:.0f}ms)")
        print(f"   错误: {e}")
        sys.exit(1)

    print("\n✅ LLM 连通性测试通过")


if __name__ == "__main__":
    main()
