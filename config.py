import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    (
        "你是用户的飞书私人助手，简洁专业。"
        "你可以通过工具访问用户的飞书日历、文档、消息、表格、任务、邮件等数据。"
        "优先调用工具获取真实数据，不编造。"
        "对于高危操作，先用 dry-run 预览再执行。"
    ),
)

MAX_HISTORY = int(os.getenv("MAX_HISTORY", "30"))
LOG_DIR = Path(os.getenv("LOG_DIR", "./logs"))
TOOL_TIMEOUT = int(os.getenv("TOOL_TIMEOUT", "30"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "1"))
MAX_AGENT_ROUNDS = int(os.getenv("MAX_AGENT_ROUNDS", "15"))

HOOKS_CUSTOM_DIR = Path(os.getenv("HOOKS_CUSTOM_DIR", "./hooks_custom"))

LOG_DIR.mkdir(parents=True, exist_ok=True)
