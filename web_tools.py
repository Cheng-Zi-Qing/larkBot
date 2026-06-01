"""Web search tools — 4-tier fallback: Tavily -> Exa -> DuckDuckGo -> Raw Fetch."""
from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request

import config
import logger
from tools import ToolDef, ToolResult, register, _schema


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tavily_available() -> bool:
    return bool(config.TAVILY_API_KEY)


def _exa_available() -> bool:
    return bool(config.EXA_API_KEY)


def _log_fallback(tool: str, engine: str, error: Exception, next_engine: str) -> None:
    """Log every fallback event for post-mortem debugging."""
    logger.log_error(
        "", tool, f"{engine}_fallback",
        stderr=f"{engine} failed ({type(error).__name__}: {error}), falling back to {next_engine}",
    )


def _has_cjk(text: str) -> bool:
    """Check if text contains CJK characters."""
    return bool(re.search(r"[一-鿿぀-ヿ가-힯]", text))


def _validate_results(query: str, formatted: str) -> str | None:
    """Basic relevance gate. Returns text if OK, None if results are garbage.

    Current checks:
    1. Empty or literal "No results found." -> None
    2. CJK query but zero CJK in snippets -> likely wrong-language garbage
    """
    if not formatted or formatted.strip() == "No results found.":
        return None

    # CJK language mismatch check
    if _has_cjk(query):
        # Extract snippet lines (indented with 3 spaces in our format)
        snippets = re.findall(r"   (.+)", formatted)
        snippet_text = " ".join(snippets)
        if snippet_text and not _has_cjk(snippet_text):
            return None

    return formatted


# ---------------------------------------------------------------------------
# Search engine implementations
# ---------------------------------------------------------------------------

def _search_tavily(query: str, max_results: int = 5) -> str:
    from tavily import TavilyClient

    client = TavilyClient(api_key=config.TAVILY_API_KEY)
    resp = client.search(query=query, max_results=max_results, include_answer=True)

    lines: list[str] = []
    if resp.get("answer"):
        lines.append(f"**摘要**: {resp['answer']}\n")
    for i, r in enumerate(resp.get("results", []), 1):
        title = r.get("title", "")
        url = r.get("url", "")
        snippet = r.get("content", "")[:300]
        lines.append(f"{i}. [{title}]({url})\n   {snippet}")
    return "\n".join(lines) or "No results found."


def _search_tavily_advanced(query: str, max_results: int = 8) -> str:
    """Tavily advanced search with answer synthesis for deep research."""
    from tavily import TavilyClient

    client = TavilyClient(api_key=config.TAVILY_API_KEY)
    resp = client.search(
        query=query,
        max_results=max_results,
        search_depth="advanced",
        include_answer=True,
        include_raw_content=False,
    )

    lines: list[str] = []
    if resp.get("answer"):
        lines.append(f"## 综合分析\n{resp['answer']}\n")
    lines.append("## 来源")
    for i, r in enumerate(resp.get("results", []), 1):
        title = r.get("title", "")
        url = r.get("url", "")
        snippet = r.get("content", "")[:400]
        lines.append(f"{i}. [{title}]({url})\n   {snippet}")
    return "\n".join(lines) or "No results found."


def _search_exa(query: str, max_results: int = 5) -> str:
    from exa_py import Exa

    client = Exa(api_key=config.EXA_API_KEY)
    resp = client.search_and_contents(
        query=query,
        num_results=max_results,
        text={"max_characters": 300},
    )

    if not resp.results:
        return "No results found."

    lines: list[str] = []
    for i, r in enumerate(resp.results, 1):
        title = r.title or ""
        url = r.url or ""
        snippet = (r.text or "")[:300]
        lines.append(f"{i}. [{title}]({url})\n   {snippet}")
    return "\n".join(lines)


def _search_ddg(query: str, max_results: int = 5) -> str:
    from duckduckgo_search import DDGS

    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=max_results))

    if not results:
        return "No results found."

    lines: list[str] = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        url = r.get("href", "")
        snippet = r.get("body", "")[:300]
        lines.append(f"{i}. [{title}]({url})\n   {snippet}")
    return "\n".join(lines)


def _search_raw_fetch(query: str, max_results: int = 5) -> str:
    """Last resort: fetch Bing search page with urllib, parse HTML for results."""
    encoded = urllib.parse.quote_plus(query)
    url = f"https://www.bing.com/search?q={encoded}&count={max_results}"
    req = urllib.request.Request(url, headers={
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    # Parse Bing result blocks (fragile but acceptable as last resort)
    blocks = re.findall(
        r'<li class="b_algo"[^>]*>.*?'
        r'<a href="([^"]*)"[^>]*>(.*?)</a>.*?'
        r'<p[^>]*>(.*?)</p>',
        html,
        re.DOTALL,
    )

    if not blocks:
        return "No results found."

    lines: list[str] = []
    for i, (href, raw_title, raw_snippet) in enumerate(blocks[:max_results], 1):
        title = re.sub(r"<[^>]+>", "", raw_title).strip()
        snippet = re.sub(r"<[^>]+>", "", raw_snippet).strip()[:300]
        lines.append(f"{i}. [{title}]({href})\n   {snippet}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Fallback chain runner
# ---------------------------------------------------------------------------

# Each entry: (display_name, search_func, availability_check_or_None)
_SEARCH_CHAIN: list[tuple[str, callable, callable | None]] = [
    ("Tavily", _search_tavily, _tavily_available),
    ("Exa", _search_exa, _exa_available),
    ("DuckDuckGo", _search_ddg, None),
    ("RawFetch", _search_raw_fetch, None),
]

_RESEARCH_CHAIN: list[tuple[str, callable, callable | None]] = [
    ("Tavily(advanced)", _search_tavily_advanced, _tavily_available),
    ("Exa", _search_exa, _exa_available),
    ("DuckDuckGo", _search_ddg, None),
    ("RawFetch", _search_raw_fetch, None),
]


def _run_search_chain(
    tool_name: str,
    query: str,
    max_results: int,
    chain: list[tuple] | None = None,
) -> str:
    """Run through the fallback chain. Raises RuntimeError if ALL engines fail.

    Raising (instead of returning an error string) lets _execute_python_tool
    set success=False, which triggers the executor's recovery logic.
    """
    if chain is None:
        chain = _SEARCH_CHAIN

    errors: list[str] = []

    for i, (name, func, available_check) in enumerate(chain):
        # Skip engines whose API key is not configured
        if available_check is not None and not available_check():
            continue

        next_name = chain[i + 1][0] if i + 1 < len(chain) else "none"

        try:
            result = func(query, max_results)
            validated = _validate_results(query, result)

            if validated is None:
                # Engine returned results but they're garbage
                reason = f"{name} returned irrelevant/empty results"
                errors.append(reason)
                _log_fallback(tool_name, name, ValueError(reason), next_name)
                continue

            # Success — prepend fallback trace if we had to skip engines
            if errors:
                prefix = " → ".join(errors)
                return f"[{prefix}, used {name}]\n\n{validated}"
            return validated

        except Exception as e:
            errors.append(f"{name}({type(e).__name__}: {e})")
            _log_fallback(tool_name, name, e, next_name)

    # ALL engines exhausted — raise so executor marks success=False
    raise RuntimeError(
        f"All search engines failed for query '{query}': {'; '.join(errors)}"
    )


# ---------------------------------------------------------------------------
# web_search — 4-tier: Tavily -> Exa -> DDG -> RawFetch -> raise
# ---------------------------------------------------------------------------

def web_search(inputs: dict) -> str:
    query = inputs["query"]
    max_results = inputs.get("max_results", 5)
    return _run_search_chain("web_search", query, max_results)


register(ToolDef(
    name="web_search",
    description="搜索互联网信息",
    identity="",
    category="research",
    label="搜索网络",
    claude_schema=_schema("web_search", "Search the web for current information on any topic", {
        "query": {"type": "string", "description": "Search query"},
        "max_results": {"type": "integer", "description": "Number of results (default 5)"},
    }, ["query"]),
    python_func=web_search,
))


# ---------------------------------------------------------------------------
# web_read — Exa primary, urllib fallback, raise on total failure
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

    text = re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:5000]


def web_read(inputs: dict) -> str:
    url = inputs["url"]
    errors: list[str] = []

    if _exa_available():
        try:
            return _read_exa(url)
        except Exception as e:
            errors.append(f"Exa({e})")
            _log_fallback("web_read", "Exa", e, "urllib")

    try:
        result = _read_urllib(url)
        if errors:
            return f"[{errors[0]}, used urllib]\n\n{result}"
        return result
    except Exception as e:
        errors.append(f"urllib({e})")
        raise RuntimeError(f"All read methods failed: {'; '.join(errors)}")


register(ToolDef(
    name="web_read",
    description="读取网页正文内容",
    identity="",
    category="research",
    label="读取网页",
    claude_schema=_schema("web_read", "Fetch and extract clean text content from a URL", {
        "url": {"type": "string", "description": "URL to read"},
    }, ["url"]),
    python_func=web_read,
))


# ---------------------------------------------------------------------------
# web_research — deep research with same 4-tier fallback
# ---------------------------------------------------------------------------

def web_research(inputs: dict) -> str:
    topic = inputs["topic"]
    max_results = inputs.get("max_results", 8)
    return _run_search_chain("web_research", topic, max_results, chain=_RESEARCH_CHAIN)


register(ToolDef(
    name="web_research",
    description="深度研究一个主题（搜索+总结）",
    identity="",
    category="research",
    label="深度调研",
    claude_schema=_schema("web_research", "Research a topic in depth — searches multiple sources and provides a comprehensive summary", {
        "topic": {"type": "string", "description": "Topic or question to research"},
        "max_results": {"type": "integer", "description": "Number of sources to analyze (default 8)"},
    }, ["topic"]),
    python_func=web_research,
))
