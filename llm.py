from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import config

_MAX_RETRIES = 3
_BASE_DELAY = 2


def _retry_on_rate_limit(func):
    def wrapper(*args, **kwargs):
        for attempt in range(_MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if "rate" not in type(e).__name__.lower() and "429" not in str(e):
                    raise
                if attempt == _MAX_RETRIES - 1:
                    raise
                delay = _BASE_DELAY * (2 ** attempt)
                time.sleep(delay)
    return wrapper


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class LLMResponse:
    text: str | None
    tool_calls: list[ToolCall]
    stop_reason: str  # "end_turn" | "tool_use"
    raw: Any = None


def _anthropic_tools(tools: list[dict]) -> list[dict]:
    return tools


def _openai_tools(tools: list[dict]) -> list[dict]:
    out = []
    for t in tools:
        out.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        })
    return out


def _openai_messages(messages: list[dict], system: str) -> list[dict]:
    out = [{"role": "system", "content": system}]
    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if role == "user" and isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "tool_result":
                    out.append({
                        "role": "tool",
                        "tool_call_id": item["tool_use_id"],
                        "content": item.get("content", ""),
                    })
        elif role == "assistant" and isinstance(content, list):
            text_parts = []
            tool_calls = []
            for block in content:
                if hasattr(block, "text"):
                    text_parts.append(block.text)
                elif hasattr(block, "type") and block.type == "tool_use":
                    tool_calls.append({
                        "id": block.id,
                        "type": "function",
                        "function": {
                            "name": block.name,
                            "arguments": json.dumps(block.input),
                        },
                    })
            m: dict[str, Any] = {"role": "assistant"}
            if text_parts:
                m["content"] = "\n".join(text_parts)
            else:
                m["content"] = None
            if tool_calls:
                m["tool_calls"] = tool_calls
            out.append(m)
        elif role == "assistant" and isinstance(content, str):
            out.append({"role": "assistant", "content": content})
        else:
            out.append({"role": role, "content": content})

    return out


class AnthropicClient:
    def __init__(self):
        import anthropic
        kwargs: dict[str, Any] = {
            "api_key": config.ANTHROPIC_API_KEY,
            "timeout": 120.0,
        }
        if config.ANTHROPIC_BASE_URL:
            kwargs["base_url"] = config.ANTHROPIC_BASE_URL
        self._client = anthropic.Anthropic(**kwargs)

    @_retry_on_rate_limit
    def chat(
        self,
        messages: list[dict],
        system: str,
        tools: list[dict],
        model: str,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        response = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            tools=_anthropic_tools(tools),
            messages=messages,
        )

        text = None
        tool_calls = []
        for block in response.content:
            if hasattr(block, "text"):
                text = block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    input=block.input,
                ))

        stop = "tool_use" if response.stop_reason == "tool_use" else "end_turn"
        return LLMResponse(text=text, tool_calls=tool_calls, stop_reason=stop, raw=response)

    def build_tool_results(self, tool_use_results: list[dict]) -> dict:
        return {"role": "user", "content": tool_use_results}

    def build_assistant_message(self, response: LLMResponse) -> dict:
        return {"role": "assistant", "content": response.raw.content}


class OpenAIClient:
    def __init__(self):
        from openai import OpenAI
        kwargs: dict[str, Any] = {
            "api_key": config.OPENAI_API_KEY,
            "timeout": 120.0,
        }
        if config.OPENAI_BASE_URL:
            kwargs["base_url"] = config.OPENAI_BASE_URL
        self._client = OpenAI(**kwargs)

    @_retry_on_rate_limit
    def chat(
        self,
        messages: list[dict],
        system: str,
        tools: list[dict],
        model: str,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        oai_messages = _openai_messages(messages, system)
        oai_tools = _openai_tools(tools)

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": oai_messages,
        }
        if oai_tools:
            kwargs["tools"] = oai_tools

        response = self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        message = choice.message

        text = message.content
        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    input=args,
                ))

        stop = "tool_use" if tool_calls else "end_turn"
        return LLMResponse(text=text, tool_calls=tool_calls, stop_reason=stop, raw=response)

    def build_tool_results(self, tool_use_results: list[dict]) -> list[dict]:
        out = []
        for r in tool_use_results:
            out.append({
                "role": "tool",
                "tool_call_id": r["tool_use_id"],
                "content": r.get("content", ""),
            })
        return out

    def build_assistant_message(self, response: LLMResponse) -> dict:
        choice = response.raw.choices[0]
        msg: dict[str, Any] = {"role": "assistant", "content": choice.message.content}
        if choice.message.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in choice.message.tool_calls
            ]
        return msg


_client: AnthropicClient | OpenAIClient | None = None


def get_client() -> AnthropicClient | OpenAIClient:
    global _client
    if _client is None:
        if config.LLM_PROVIDER == "anthropic":
            _client = AnthropicClient()
        else:
            _client = OpenAIClient()
    return _client
