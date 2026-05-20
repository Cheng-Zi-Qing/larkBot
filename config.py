import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- LLM Provider ---
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")  # anthropic | openai

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "")

_DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-20250514",
    "openai": "gpt-4o",
}
LLM_MODEL = os.getenv("LLM_MODEL", "") or _DEFAULT_MODELS.get(LLM_PROVIDER, "")

SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    (
        "你是用户的飞书私人助手，简洁专业。"
        "你可以通过工具访问用户的飞书日历、文档、消息、表格、任务、邮件等数据。"
        "优先调用工具获取真实数据，不编造。"
        "对于高危操作，先用 dry-run 预览再执行。"
    ),
)

# --- Bot settings ---
MAX_HISTORY = int(os.getenv("MAX_HISTORY", "30"))
LOG_DIR = Path(os.getenv("LOG_DIR", "./logs"))
TOOL_TIMEOUT = int(os.getenv("TOOL_TIMEOUT", "30"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "1"))
MAX_AGENT_ROUNDS = int(os.getenv("MAX_AGENT_ROUNDS", "15"))
HOOKS_CUSTOM_DIR = Path(os.getenv("HOOKS_CUSTOM_DIR", "./hooks_custom"))

# --- Web Search ---
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
EXA_API_KEY = os.getenv("EXA_API_KEY", "")

LOG_DIR.mkdir(parents=True, exist_ok=True)


def validate():
    if LLM_PROVIDER == "anthropic" and not ANTHROPIC_API_KEY:
        print("ERROR: LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set", file=sys.stderr)
        print("Run 'make init' to configure.", file=sys.stderr)
        sys.exit(1)
    if LLM_PROVIDER == "openai" and not OPENAI_API_KEY:
        print("ERROR: LLM_PROVIDER=openai but OPENAI_API_KEY is not set", file=sys.stderr)
        print("Run 'make init' to configure.", file=sys.stderr)
        sys.exit(1)
    if LLM_PROVIDER not in ("anthropic", "openai"):
        print(f"ERROR: Unknown LLM_PROVIDER: {LLM_PROVIDER}", file=sys.stderr)
        sys.exit(1)
