"""Shared helpers for persona tools."""
from __future__ import annotations

from tools import execute_tool, ToolResult


def call_tool(
    request_id: str, name: str, inputs: dict,
    chat_id: str = "", user_id: str = "",
) -> str:
    result: ToolResult = execute_tool(request_id, name, inputs, chat_id, user_id)
    return result.output


def safe_call(
    request_id: str, name: str, inputs: dict,
    chat_id: str = "", user_id: str = "",
) -> str:
    try:
        return call_tool(request_id, name, inputs, chat_id, user_id)
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


def save_to_doc(
    request_id: str, title: str, content: str,
    chat_id: str = "", user_id: str = "",
) -> str:
    return call_tool(request_id, "create_doc", {"title": title, "content": content}, chat_id, user_id)
