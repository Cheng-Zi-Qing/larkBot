from __future__ import annotations

from . import assistant, pm, analyst, ops  # noqa: F401 — registers tools

PERSONA_CATEGORIES: dict[str, set[str] | None] = {
    "assistant": None,  # all categories
    "pm": {"read", "write", "organize", "research"},
    "analyst": {"read", "write", "research"},
    "ops": {"read", "write", "organize", "communicate", "research"},
    "reviewer": {"read", "research"},
}
