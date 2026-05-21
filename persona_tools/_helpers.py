"""Shared helpers for persona tools."""
from __future__ import annotations

from tools import execute_tool, ToolResult


def call_tool(request_id: str, name: str, inputs: dict) -> str:
    result: ToolResult = execute_tool(request_id, name, inputs)
    return result.output


def safe_call(request_id: str, name: str, inputs: dict) -> str:
    try:
        return call_tool(request_id, name, inputs)
    except Exception:
        return ""


def llm_generate(prompt: str, system: str) -> str:
    import config
    import llm
    client = llm.get_client()
    response = client.chat(
        messages=[{"role": "user", "content": prompt}],
        system=system,
        tools=[],
        model=config.LLM_SUMMARY_MODEL,
        max_tokens=4096,
    )
    return response.text or ""


def save_to_doc(request_id: str, title: str, content: str) -> str:
    result = call_tool(request_id, "create_doc", {"title": title, "content": content})
    return result
