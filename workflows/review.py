"""审查类 workflows — 两轮模式：零搜索审读 + 定向验证。"""
from __future__ import annotations

from workflows import WorkflowDef, register

register(WorkflowDef(
    id="report_review",
    name="报告审查（第一轮）",
    persona="reviewer",
    trigger_patterns=[
        "审查", "review", "帮我审", "审一下",
        "审稿", "核查", "挑毛病",
    ],
    steps=[
        "读取被审文档（read_doc/search_docs/直接文本）",
        "零搜索纯推理：三维度审读（事实/推理/落地）",
        "输出怀疑清单（聊天回复，不写文档）：总体印象 + 按严重度排列的条目",
        "等待用户指定验证编号",
    ],
    tools_hint=["read_doc", "search_docs"],
    output_template=(
        "## 总体印象\n"
        "{一句话定性最大风险}\n"
        "优先验证：#N #N\n\n"
        "## 怀疑清单\n"
        "#1 🔴 [事实] 「{引用}」{节名} — {理由}\n"
        "#2 🟠 [落地] {隐含假设} — {崩塌后果}\n"
        "#3 🟡 [推理] 「{断言}」{节名} — {谬误名}"
    ),
))

register(WorkflowDef(
    id="review_verify",
    name="定向验证（第二轮）",
    persona="reviewer",
    trigger_patterns=[
        "验证 #", "验证 全部", "verify",
    ],
    steps=[
        "根据用户指定编号，从怀疑清单提取待验证条目",
        "逐条 web_search 定向验证：独立找原始出处，不信原文引用",
        "标注验证结果：✅已证实 / ⚠️部分偏差 / ❌证伪 / 📅数据过时",
        "create_doc 写入正式审查报告到飞书文档",
    ],
    tools_hint=["web_search", "web_research", "web_read", "create_doc"],
    output_template=(
        "## 审查报告\n"
        "### 总评（🔴/🟠/🟡 + 统计）\n"
        "### 验证结果\n"
        "| # | 原文断言 | 验证结果 | 出处 | 判定 |\n"
        "### 修正建议（按优先级）"
    ),
))
