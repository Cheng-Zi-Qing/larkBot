from __future__ import annotations

import os

if os.environ.get("AGENT_LEGACY"):
    from agent._legacy import run, history, _confirmed_plans, _plans_lock  # noqa: F401
else:
    from agent.loop import run  # noqa: F401
    from agent.history import history  # noqa: F401
    from agent.planner import _confirmed_plans, _plans_lock  # noqa: F401
