"""内容策划 workflow."""
from __future__ import annotations

from workflows import WorkflowDef, register

register(WorkflowDef(
    id="content_plan",
    name="内容策划方案",
    persona="ops",
    trigger_patterns=[
        "内容策划", "内容运营", "内容方案", "content plan",
        "选题", "内容日历",
    ],
    steps=[
        "搜索目标话题热门内容和趋势",
        "搜索受众痛点和常见问题",
        "搜索竞品内容策略和发布频率",
        "搜索 SEO 关键词机会",
        "搜索内部品牌指南和素材库",
        "按 AIDA 框架组织内容策划方案",
        "生成 4 周选题日历",
        "保存为飞书文档（如要求）",
    ],
    tools_hint=["web_search", "web_research", "search_docs", "search_messages", "create_doc"],
    output_template=(
        "## 受众分析（画像/痛点/消费习惯）\n"
        "## 平台适配（平台/格式/频率/调性）\n"
        "## 选题规划 4 周（周/选题/类型/目标）\n"
        "## SEO 机会（关键词/搜索量/竞争度/建议内容）\n"
        "## 竞品内容审计（竞对/频率/热门/可借鉴）\n"
        "## AIDA 选题详情（每个选题的 Hook+兴趣+欲望+行动）"
    ),
))

register(WorkflowDef(
    id="growth_plan",
    name="增长方案",
    persona="ops",
    trigger_patterns=[
        "增长方案", "冷启动", "获客", "growth",
        "拓客", "用户增长",
    ],
    steps=[
        "搜索目标产品类型的获客策略",
        "搜索竞品增长打法",
        "搜索 PLG vs SLG 路径参考",
        "搜索 First 100 Customers 案例",
        "渠道评估：Bull's Eye 筛选（外圈→中圈→靶心）",
        "输出 ICP + 渠道矩阵 + 冷启动 playbook",
        "设计 2-3 个增长实验",
    ],
    tools_hint=["web_research", "web_search", "search_docs", "recall_memory"],
    output_template=(
        "## ICP（公司画像/决策者/影响者/触发点/反面画像）\n"
        "## 竞品获客方式（表格）\n"
        "## 渠道评估矩阵（渠道/CAC/LTV/可扩展性/难度/评分）\n"
        "## Bull's Eye 渠道筛选（内圈/中圈/外圈）\n"
        "## First 100 Customers 方案\n"
        "## 增长实验设计（实验名/假设/指标/时长/预算）"
    ),
))
