from __future__ import annotations

import os
import sys

if os.environ.get("BOT_LEGACY"):
    from bot._legacy import main, TOOL_LABELS, handle_message  # noqa: F401
else:
    from bot.formatter import TOOL_LABELS  # noqa: F401
    from bot.router import handle_message  # noqa: F401

    # Side-effect imports: register tools
    import web_tools  # noqa: F401
    import memory  # noqa: F401
    import persona_tools  # noqa: F401
    import plan_tool  # noqa: F401

    def main():
        """Bot 入口：启动 event consumer + 主循环。"""
        import json
        import config
        import hooks
        import logger
        from bot.consumer import start_event_consumer, shutdown_consumer
        from bot.router import handle_message as _handle, _executor, shutdown

        config.validate()
        hooks.load_custom_hooks()
        proc = start_event_consumer()
        print("[BOT] Listening for messages...", file=sys.stderr)

        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    _executor.submit(_handle, event)
                except json.JSONDecodeError:
                    logger.log_error("system", "bot", "json_parse", stderr=f"Bad line: {line[:200]}")
        except KeyboardInterrupt:
            print("\n[BOT] Shutting down...", file=sys.stderr)
        finally:
            shutdown()
            shutdown_consumer(proc)


if __name__ == "__main__":
    main()
