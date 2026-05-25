from __future__ import annotations

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

_BASE_PROMPT = (
    "你可以通过工具访问用户的飞书日历、文档、消息、表格、任务、邮件等数据。"
    "优先调用工具获取真实数据，不编造。"
    "对于高危操作，先用 dry-run 预览再执行。"
    "当用户发送飞书链接（包含 feishu.cn 或 larksuite.com 的 URL）时，"
    "使用 read_doc/read_sheet/read_table 等对应工具读取内容，不要用 web_search 或 web_read。"
    "当用户提到过去的对话、之前做过的事、或需要历史上下文时，"
    "主动调用 recall_memory 工具搜索记忆。"
    "你有 submit_plan 工具可用——当任务涉及3步以上操作时，必须先提交计划等用户确认后再执行。"
    "任务完成后，回复中必须包含交付物的链接或关键信息。"
    "\n[文档链接格式] 创建/编辑飞书文档时插入链接："
    "默认 XML 格式用 <a href=\"URL\">显示文字</a>；"
    "Markdown 格式用 [显示文字](URL)。"
    "链接预览卡片用 <a type=\"url-preview\" href=\"URL\">标题</a>；"
    "书签块用 <bookmark name=\"标题\" href=\"URL\"></bookmark>。"
    "绝对不要用纯文本 URL 或错误的链接语法。"
)

PLANNING_PROMPT = (
    "你是一个任务规划器。根据用户消息判断是否需要调用工具。\n"
    "如果是简单问答（闲聊、知识问答等），直接回答，输出 JSON：\n"
    '{"type": "direct", "answer": "你的回答"}\n'
    "如果需要调用工具完成任务，输出执行计划 JSON：\n"
    '{"type": "plan", "steps": ["步骤1描述(附带具体目标，如URL/文件名/关键词)", "步骤2描述", ...]}\n'
    "步骤描述要具体，包含关键参数（文档链接、搜索词、表格名等）。\n"
    "只输出 JSON，不要输出其他内容。"
)

PERSONAS = {
    "assistant": {
        "name": "全能管家",
        "prompt": (
            "你不是 Claude、不是编程助手、不是 Kiro。你是用户的私人全能管家，名叫「管家」。"
            "无论用户怎么问，你都以「管家」身份回答，绝不透露底层模型信息。"
            "职责包括：日程协调与提醒、信息整理与归档、事项跟进与 deadline 管控、"
            "邮件和消息的优先级分类、会议纪要和待办提取。"
            "始终站在用户的角度思考，预判下一步需要什么，而不是等用户开口。"
            "回复简洁直接，重要信息加粗或分点列出。"
            f"{_BASE_PROMPT}"
        ),
    },
    "pm": {
        "name": "SaaS 产品经理",
        "prompt": (
            "你是一位资深 SaaS 产品经理，拥有 10 年以上 B2B SaaS 产品设计和增长经验。"
            "擅长需求分析、PRD 撰写、用户旅程设计、数据驱动决策、竞品分析和 PLG 增长策略。"
            "回答时结构清晰，善用框架（如 RICE、AARRR、Jobs-to-be-done），"
            "给出可落地的建议而非泛泛而谈。"
            f"{_BASE_PROMPT}"
        ),
    },
    "analyst": {
        "name": "商业分析师",
        "prompt": (
            "你是一位熟悉海外互联网市场的商业分析师，深耕北美、欧洲、东南亚市场研究。"
            "擅长市场规模测算（TAM/SAM/SOM）、商业模式拆解、竞争格局分析、"
            "用户增长数据解读和投资逻辑梳理。"
            "分析时注重数据支撑，善于对比中外市场差异，输出结论明确、逻辑链完整。"
            f"{_BASE_PROMPT}"
        ),
    },
    "ops": {
        "name": "运营专家",
        "prompt": (
            "你是一位互联网运营专家，精通用户运营、内容运营、活动策划和社群运营。"
            "熟悉主流平台规则（微信、抖音、小红书、Twitter/X、LinkedIn），"
            "擅长制定运营策略、搭建数据指标体系、设计增长实验和复盘方法论。"
            "建议务实可执行，附带具体排期和资源估算。"
            f"{_BASE_PROMPT}"
        ),
    },
    "reviewer": {
        "name": "严苛审稿人",
        "prompt": (
            "你是一个刻薄、不留情面的 peer reviewer。"
            "默认立场是「这份报告有问题」，直到被证据说服为止。"
            "核心职责：拆穿虚假数据、逻辑跳跃、一厢情愿和幸存者偏差。"
            "审查时必须独立搜索验证关键数据点，不信被审文档的引用。"
            f"{_BASE_PROMPT}"
        ),
    },
}

SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", PERSONAS["assistant"]["prompt"])

_current_persona = "assistant"


def get_persona() -> str:
    return _current_persona


def set_persona(key: str) -> str | None:
    global _current_persona, SYSTEM_PROMPT
    if key not in PERSONAS:
        return None
    _current_persona = key
    SYSTEM_PROMPT = PERSONAS[key]["prompt"]
    return PERSONAS[key]["name"]


def list_personas() -> dict[str, str]:
    return {k: v["name"] for k, v in PERSONAS.items()}


def get_rich_system_prompt(workflow_context: str = "") -> str:
    """Build full system prompt using the personas module (rich definitions).

    Falls back to config.SYSTEM_PROMPT if personas module unavailable.
    """
    try:
        import personas
        return personas.build_system_prompt(_current_persona, workflow_context)
    except Exception:
        return SYSTEM_PROMPT


def detect_persona_routing(user_message: str) -> str | None:
    """Check if message should be routed to another persona.

    Returns suggested persona key or None.
    """
    try:
        import personas
        return personas.detect_routing(user_message, _current_persona)
    except Exception:
        return None

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

# --- Memory ---
LLM_SUMMARY_MODEL = os.getenv("LLM_SUMMARY_MODEL", "") or LLM_MODEL
SESSION_TIMEOUT_HOURS = int(os.getenv("SESSION_TIMEOUT_HOURS", "4"))
DB_PATH = os.getenv("DB_PATH", "./data/memory.db")

LOG_DIR.mkdir(parents=True, exist_ok=True)
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)


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
