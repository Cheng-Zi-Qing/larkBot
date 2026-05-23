"""PRD 生成 workflow."""
from __future__ import annotations

from workflows import WorkflowDef, register

register(WorkflowDef(
    id="prd",
    name="PRD 生成",
    persona="pm",
    trigger_patterns=[
        "prd", "产品需求文档", "需求文档", "写prd", "写 prd",
        "需求分析",
    ],
    steps=[
        "搜索内部相关文档（drive+search）",
        "搜索团队讨论记录（search_messages）",
        "搜索相关任务（search_tasks）",
        "回忆历史对话（recall_memory）",
        "JTBD 分析：当[场景]，用户想要[行动]，以便[结果]",
        "按 8 节模板生成 PRD",
        "RICE 优先级排序所有需求项",
        "可选：拆解为飞书任务（create_task）",
        "保存为飞书文档",
    ],
    tools_hint=["search_docs", "search_messages", "search_tasks", "recall_memory", "web_search", "create_doc", "create_task"],
    output_template=(
        "## 1. 问题定义（Who/What/Why/Evidence）\n"
        "## 2. JTBD 分析\n"
        "## 3. 用户故事 & 验收标准\n"
        "## 4. 功能需求（RICE 排序表）\n"
        "## 5. 非功能需求\n"
        "## 6. 成功指标（North Star + Guardrails）\n"
        "## 7. GTM 路径\n"
        "## 8. 里程碑（阶段/交付物/时间/验收标准）"
    ),
))
