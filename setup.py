#!/usr/bin/env python3
"""larkBot interactive setup wizard."""

import json
import shutil
import subprocess
from pathlib import Path

ENV_PATH = Path(__file__).parent / ".env"

ANTHROPIC_MODELS = [
    ("claude-sonnet-4-20250514", "Claude Sonnet 4 (推荐)"),
    ("claude-opus-4-20250514", "Claude Opus 4"),
    ("claude-haiku-4-20250514", "Claude Haiku 4"),
]

OPENAI_MODELS = [
    ("gpt-4o", "GPT-4o (推荐)"),
    ("gpt-4o-mini", "GPT-4o Mini"),
    ("gpt-4-turbo", "GPT-4 Turbo"),
]


def ask_choice(prompt: str, options: list[tuple[str, str]], allow_custom: bool = False) -> str:
    print(f"\n{prompt}")
    for i, (_, label) in enumerate(options, 1):
        print(f"  {i}) {label}")
    if allow_custom:
        print(f"  {len(options) + 1}) 自定义输入")

    while True:
        try:
            raw = input("> ").strip()
            idx = int(raw)
            if 1 <= idx <= len(options):
                return options[idx - 1][0]
            if allow_custom and idx == len(options) + 1:
                return input("  输入自定义值: ").strip()
        except (ValueError, EOFError):
            pass
        print("  请输入有效的选项编号")


def ask_input(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    print(f"\n{prompt}{suffix}")
    try:
        value = input("> ").strip()
    except EOFError:
        value = ""
    return value or default


def check_lark_cli() -> dict:
    result = {"installed": False, "configured": False, "bot_ready": False, "user_ready": False}

    if not shutil.which("lark-cli"):
        return result
    result["installed"] = True

    try:
        proc = subprocess.run(
            ["lark-cli", "auth", "status"],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode != 0:
            return result

        data = json.loads(proc.stdout)
        result["configured"] = True
        result["app_id"] = data.get("appId", "")

        identities = data.get("identities", {})
        result["bot_ready"] = identities.get("bot", {}).get("available", False)
        result["user_ready"] = identities.get("user", {}).get("available", False)
        result["user_name"] = data.get("userName", "")
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        pass

    return result


def verify_anthropic_key(api_key: str, model: str, base_url: str = "") -> bool:
    try:
        import anthropic
        kwargs = {"api_key": api_key, "timeout": 15.0}
        if base_url:
            kwargs["base_url"] = base_url
        print("  正在连接...", end="", flush=True)
        client = anthropic.Anthropic(**kwargs)
        client.messages.create(
            model=model, max_tokens=10,
            messages=[{"role": "user", "content": "hi"}],
        )
        print("\r", end="")
        return True
    except KeyboardInterrupt:
        print("\n  已取消")
        return False
    except Exception as e:
        print(f"\r  验证失败: {e}")
        return False


def verify_openai_key(api_key: str, model: str, base_url: str = "") -> bool:
    try:
        from openai import OpenAI
        kwargs = {"api_key": api_key, "timeout": 15.0}
        if base_url:
            kwargs["base_url"] = base_url
        print("  正在连接...", end="", flush=True)
        client = OpenAI(**kwargs)
        client.chat.completions.create(
            model=model, max_tokens=10,
            messages=[{"role": "user", "content": "hi"}],
        )
        print("\r", end="")
        return True
    except KeyboardInterrupt:
        print("\n  已取消")
        return False
    except Exception as e:
        print(f"\r  验证失败: {e}")
        return False


def write_env(values: dict):
    lines = [
        "# larkBot 配置 (由 setup.py 生成)",
        f"LLM_PROVIDER={values['provider']}",
        "",
    ]

    if values["provider"] == "anthropic":
        lines.append(f"ANTHROPIC_API_KEY={values['api_key']}")
        if values.get("base_url"):
            lines.append(f"ANTHROPIC_BASE_URL={values['base_url']}")
    else:
        lines.append(f"OPENAI_API_KEY={values['api_key']}")
        if values.get("base_url"):
            lines.append(f"OPENAI_BASE_URL={values['base_url']}")

    lines += [
        f"LLM_MODEL={values['model']}",
        "",
        "# Bot 设置",
        "MAX_HISTORY=30",
        "LOG_DIR=./logs",
        "TOOL_TIMEOUT=30",
        "MAX_RETRIES=1",
        "MAX_AGENT_ROUNDS=15",
        "HOOKS_CUSTOM_DIR=./hooks_custom",
        "",
        "# Web 搜索 (可选)",
    ]
    if values.get("tavily_key"):
        lines.append(f"TAVILY_API_KEY={values['tavily_key']}")
    else:
        lines.append("# TAVILY_API_KEY=")
    if values.get("exa_key"):
        lines.append(f"EXA_API_KEY={values['exa_key']}")
    else:
        lines.append("# EXA_API_KEY=")
    lines.append("")

    ENV_PATH.write_text("\n".join(lines), encoding="utf-8")


def main():
    print("=" * 40)
    print("  larkBot 初始化配置")
    print("=" * 40)

    if ENV_PATH.exists():
        print(f"\n.env 文件已存在: {ENV_PATH}")
        overwrite = input("是否覆盖? (y/N) > ").strip().lower()
        if overwrite != "y":
            print("已取消")
            return

    # [1] Provider
    provider_options = [
        ("anthropic", "Anthropic (Claude)"),
        ("anthropic_compat", "Anthropic 兼容 (自定义 Base URL)"),
        ("openai", "OpenAI"),
        ("openai_compat", "OpenAI 兼容 (DeepSeek / 通义千问 / 本地模型等)"),
    ]
    choice = ask_choice("[1] 选择 LLM 提供商:", provider_options)
    is_openai_compat = choice == "openai_compat"
    is_anthropic_compat = choice == "anthropic_compat"
    provider = "openai" if is_openai_compat else ("anthropic" if is_anthropic_compat else choice)

    values = {"provider": provider, "api_key": "", "model": "", "base_url": "", "base_url_key": ""}
    step = 2

    # [2] Base URL (compatible modes)
    if is_openai_compat:
        values["base_url"] = ask_input(
            f"[{step}] 输入 API Base URL (如 https://api.deepseek.com):"
        )
        values["base_url_key"] = "OPENAI_BASE_URL"
        step += 1
    elif is_anthropic_compat:
        values["base_url"] = ask_input(
            f"[{step}] 输入 API Base URL (如 https://your-proxy.com):"
        )
        values["base_url_key"] = "ANTHROPIC_BASE_URL"
        step += 1

    # [N] API Key
    if provider == "anthropic":
        values["api_key"] = ask_input(f"[{step}] 输入 Anthropic API Key:")
    else:
        values["api_key"] = ask_input(f"[{step}] 输入 API Key:")
    step += 1

    # [N] Model
    if provider == "anthropic" and not is_anthropic_compat:
        values["model"] = ask_choice(
            f"[{step}] 选择模型:", ANTHROPIC_MODELS, allow_custom=True
        )
    elif provider == "anthropic" and is_anthropic_compat:
        values["model"] = ask_input(
            f"[{step}] 输入模型名 (如 claude-sonnet-4-20250514):",
            default="claude-sonnet-4-20250514",
        )
    elif is_openai_compat:
        values["model"] = ask_input(f"[{step}] 输入模型名 (如 deepseek-chat):")
    else:
        values["model"] = ask_choice(
            f"[{step}] 选择模型:", OPENAI_MODELS, allow_custom=True
        )
    step += 1

    # [N] Verify API Key
    print(f"\n[{step}] 验证 API Key...")
    if provider == "anthropic":
        ok = verify_anthropic_key(values["api_key"], values["model"], values.get("base_url", ""))
    else:
        ok = verify_openai_key(values["api_key"], values["model"], values.get("base_url", ""))

    if ok:
        print("  ✓ API Key 有效")
    else:
        proceed = input("  验证失败，是否仍然继续? (y/N) > ").strip().lower()
        if proceed != "y":
            print("已取消")
            return
    step += 1

    # [N] lark-cli check
    print(f"\n[{step}] 检查 lark-cli 状态...")
    lark = check_lark_cli()

    if lark["installed"]:
        print("  ✓ lark-cli 已安装")
    else:
        print("  ✗ lark-cli 未安装")
        print("    运行: npx @larksuite/cli@latest install")

    if lark["configured"]:
        print(f"  ✓ 应用已配置 ({lark.get('app_id', '?')})")
    elif lark["installed"]:
        print("  ✗ 应用未配置")
        print("    运行: lark-cli config init --new")

    if lark["bot_ready"]:
        print("  ✓ Bot 身份可用")
    elif lark["configured"]:
        print("  ✗ Bot 身份不可用 — 请在飞书后台开启机器人能力")

    if lark["user_ready"]:
        name = lark.get("user_name", "")
        print(f"  ✓ User 身份可用{f' ({name})' if name else ''}")
    elif lark["configured"]:
        print("  ✗ User 身份不可用")
        print("    运行: lark-cli auth login --recommend")
    step += 1

    # [N] Web search (optional)
    print(f"\n[{step}] Web 搜索配置 (可选，回车跳过)")
    tavily_key = ask_input("  Tavily API Key (https://tavily.com, 回车跳过):")
    exa_key = ask_input("  Exa API Key (https://exa.ai, 回车跳过):")
    values["tavily_key"] = tavily_key
    values["exa_key"] = exa_key
    if not tavily_key and not exa_key:
        print("  → 将使用 DuckDuckGo 免费搜索")

    # Write .env
    write_env(values)
    print(f"\n✅ 配置已写入 {ENV_PATH}")
    print("   运行 make start 启动 bot")


if __name__ == "__main__":
    main()
