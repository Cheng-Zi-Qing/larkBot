from __future__ import annotations

from . import assistant, pm, analyst, ops  # noqa: F401 — registers tools

PERSONA_TOOLS: dict[str, list[str] | None] = {
    "assistant": None,
    "pm": [
        "search_messages", "search_chats",
        "create_doc", "read_doc", "search_docs",
        "read_table", "query_table",
        "get_agenda",
        "get_my_tasks", "create_task", "search_tasks",
        "search_user", "search_meetings",
        "web_search", "web_read", "web_research",
        "recall_memory",
        "competitive_landscape", "generate_prd",
    ],
    "analyst": [
        "search_messages",
        "read_doc", "search_docs",
        "read_table",
        "web_search", "web_read", "web_research",
        "recall_memory",
        "market_scanner", "acquisition_research",
    ],
    "ops": [
        "search_messages", "search_chats",
        "create_doc", "read_doc", "search_docs",
        "read_table", "write_table", "query_table", "read_sheet",
        "get_agenda",
        "get_my_tasks", "create_task", "search_tasks",
        "web_search", "web_read", "web_research",
        "recall_memory",
        "content_research_brief", "campaign_tracker",
    ],
}
