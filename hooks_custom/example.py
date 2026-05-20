# Custom Hook 示例
#
# 文件名以 .py 结尾即可被自动加载。
# 使用 hooks.hook 装饰器注册到任意 hook 点。
# 建议函数名以 custom_ 开头，方便 reload 时清理。

from hooks import hook, HookContext, HookResult


@hook("after_tool", priority=50)
def custom_log_slow_calls(ctx: HookContext) -> HookResult:
    """记录耗时超过 5 秒的工具调用"""
    if ctx.duration_ms > 5000:
        print(f"[SLOW] {ctx.tool_name} took {ctx.duration_ms:.0f}ms")
    return HookResult()
