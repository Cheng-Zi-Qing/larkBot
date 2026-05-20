"""Web search tools — Tavily (primary) + DuckDuckGo (fallback), Exa reader, Tavily research."""
from __future__ import annotations

import json
import urllib.request
import urllib.error

import config
from tools import ToolDef, ToolResult, register, _schema


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tavily_available() -> bool:
    return bool(config.TAVILY_API_KEY)


def _exa_available() -> bool:
    return bool(config.EXA_API_KEY)


# ---------------------------------------------------------------------------
# web_search — Tavily primary, DuckDuckGo fallback
# ---------------------------------------------------------------------------

def _search_tavily(query: str, max_results: int = 5) -> str:
    from tavily import TavilyClient
    client = TavilyClient(api_key=config.TAVILY_API_KEY)
    resp = client.search(query=query, max_results=max_results, include_answer=True)

    lines = []
    if resp.get("answer"):
        lines.append(f"**摘要**: {resp['answer']}\n")
    for i, r in enumerate(resp.get("results", []), 1):
        title = r.get("title", "")
        url = r.get("url", "")
        snippet = r.get("content", "")[:300]
        lines.append(f"{i}. [{title}]({url})\n   {snippet}")
    return "\n".join(lines) or "No results found."


def _search_ddg(query: str, max_results: int = 5) -> str:
    from duckduckgo_search import DDGS
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=max_results))

    if not results:
        return "No results found."

    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        url = r.get("href", "")
        snippet = r.get("body", "")[:300]
        lines.append(f"{i}. [{title}]({url})\n   {snippet}")
    return "\n".join(lines)


def web_search(inputs: dict) -> str:
    query = inputs["query"]
    max_results = inputs.get("max_results", 5)

    if _tavily_available():
        try:
            return _search_tavily(query, max_results)
        except Exception as e:
            fallback_reason = f"Tavily failed ({e}), falling back to DuckDuckGo"
    else:
        fallback_reason = "Tavily not configured, using DuckDuckGo"

    try:
        result = _search_ddg(query, max_results)
        return f"[{fallback_reason}]\n\n{result}"
    except Exception as e:
        return f"Search failed: {e}"


register(ToolDef(
    name="web_search",
    description="搜索互联网信息",
    identity="",
    claude_schema=_schema("web_search", "Search the web for current information on any topic", {
        "query": {"type": "string", "description": "Search query"},
        "max_results": {"type": "integer", "description": "Number of results (default 5)"},
    }, ["query"]),
    python_func=web_search,
))


# ---------------------------------------------------------------------------
# web_read — Exa primary, urllib fallback
# ---------------------------------------------------------------------------

def _read_exa(url: str) -> str:
    from exa_py import Exa
    client = Exa(api_key=config.EXA_API_KEY)
    resp = client.get_contents([url], text={"max_characters": 5000})
    if resp.results:
        r = resp.results[0]
        title = r.title or ""
        text = r.text or ""
        return f"# {title}\n\n{text}" if title else text
    return "No content extracted."


def _read_urllib(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "larkBot/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8", errors="replace")

    # Basic HTML tag stripping
    import re
    text = re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:5000]


def web_read(inputs: dict) -> str:
    url = inputs["url"]

    if _exa_available():
        try:
            return _read_exa(url)
        except Exception as e:
            fallback_reason = f"Exa failed ({e}), falling back to direct fetch"
    else:
        fallback_reason = ""

    try:
        result = _read_urllib(url)
        if fallback_reason:
            return f"[{fallback_reason}]\n\n{result}"
        return result
    except Exception as e:
        return f"Failed to read URL: {e}"


register(ToolDef(
    name="web_read",
    description="读取网页正文内容",
    identity="",
    claude_schema=_schema("web_read", "Fetch and extract clean text content from a URL", {
        "url": {"type": "string", "description": "URL to read"},
    }, ["url"]),
    python_func=web_read,
))


# ---------------------------------------------------------------------------
# web_research — Tavily deep research (search + summarize), DDG fallback
# ---------------------------------------------------------------------------

def web_research(inputs: dict) -> str:
    topic = inputs["topic"]
    max_results = inputs.get("max_results", 8)

    if _tavily_available():
        try:
            from tavily import TavilyClient
            client = TavilyClient(api_key=config.TAVILY_API_KEY)
            resp = client.search(
                query=topic,
                max_results=max_results,
                search_depth="advanced",
                include_answer=True,
                include_raw_content=False,
            )

            lines = []
            if resp.get("answer"):
                lines.append(f"## 综合分析\n{resp['answer']}\n")
            lines.append("## 来源")
            for i, r in enumerate(resp.get("results", []), 1):
                title = r.get("title", "")
                url = r.get("url", "")
                snippet = r.get("content", "")[:400]
                lines.append(f"{i}. [{title}]({url})\n   {snippet}")
            return "\n".join(lines)
        except Exception as e:
            pass

    # Fallback: DDG search
    try:
        return f"[Tavily unavailable, using DuckDuckGo basic search]\n\n{_search_ddg(topic, max_results)}"
    except Exception as e:
        return f"Research failed: {e}"


register(ToolDef(
    name="web_research",
    description="深度研究一个主题（搜索+总结）",
    identity="",
    claude_schema=_schema("web_research", "Research a topic in depth — searches multiple sources and provides a comprehensive summary", {
        "topic": {"type": "string", "description": "Topic or question to research"},
        "max_results": {"type": "integer", "description": "Number of sources to analyze (default 8)"},
    }, ["topic"]),
    python_func=web_research,
))
