"""Persona registry — rich persona definitions with routing and workflow support."""
from __future__ import annotations

from typing import Optional

from .base import PersonaDef, BASE_RULES
from . import assistant, analyst, pm, ops


_REGISTRY: dict[str, PersonaDef] = {}


def register(persona: PersonaDef):
    _REGISTRY[persona.key] = persona


def get(key: str) -> Optional[PersonaDef]:
    return _REGISTRY.get(key)


def list_all() -> dict[str, str]:
    return {k: v.name for k, v in _REGISTRY.items()}


def build_system_prompt(key: str, workflow_context: str = "") -> str:
    """Assemble full system prompt for a persona.

    Combines: persona prompt + base rules + optional workflow context + upstream snippets.
    """
    persona = _REGISTRY.get(key)
    if not persona:
        persona = _REGISTRY["assistant"]

    parts = [persona.prompt]

    # Inject upstream persona frameworks (silent borrowing)
    for up_key in persona.upstream:
        up = _REGISTRY.get(up_key)
        if up and up.thinking_frameworks:
            parts.append(
                f"\n[可借用的{up.name}框架] "
                + "；".join(up.thinking_frameworks[:3])
            )

    parts.append(f"\n{BASE_RULES}")

    if workflow_context:
        parts.append(f"\n{workflow_context}")

    return "\n".join(parts)


def detect_routing(user_message: str, current_key: str) -> Optional[str]:
    """Check if user message matches another persona's routing signals.

    Returns suggested persona key or None.
    """
    msg_lower = user_message.lower()
    for key, persona in _REGISTRY.items():
        if key == current_key:
            continue
        for signal in persona.routing_signals:
            if signal in msg_lower:
                return key
    return None


# Register all personas on import
register(assistant.PERSONA)
register(analyst.PERSONA)
register(pm.PERSONA)
register(ops.PERSONA)
