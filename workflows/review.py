"""审查类 workflows — full review, data check, logic review, feasibility challenge."""
from __future__ import annotations

from workflows import WorkflowDef, register

register(WorkflowDef(
    id="full_review",
    name="全面审查",
    persona="reviewer",
    trigger_patterns=[
        "全面审查", "审查报告", "review", "帮我审",
        "看看这份", "审一下",
    ],
    steps=[
        "读取被审文档，提取所有关键数据点和因果断言",
        "阶段1-数据真实性：逐条独立搜索验证关键数据（web_search），标注✅/⚠️/❌/📅",
        "阶段2-逻辑链拆解：提取每条推论链（前提A+B→结论C），逐条检验因果关系",
        "阶段3-可行性压力测试：对执行计划逐项追问（人力/时间/资金/竞争/技术），构造最坏场景",
        "阶段4-认知偏差扫描：检测乐观比例、反面证据、案例平衡、时间线",
        "输出审查报告：总评 + 数据真实性表 + 逻辑问题 + 可行性挑战 + 偏差 + 修正建议",
    ],
    tools_hint=["web_search", "web_research", "web_read", "search_docs", "read_doc", "create_doc"],
    output_template=(
        "## 总评（🔴/🟠/🟡/🟢 + 问题统计）\n"
        "## 一、数据真实性（表格：原文数据/验证结果/出处/判定）\n"
        "## 二、逻辑问题（逐条：级别/原文/拆解/问题/反事实）\n"
        "## 三、可行性挑战（逐条：级别/原文计划/追问/最坏情况）\n"
        "## 四、认知偏差（表格：偏差类型/证据/级别）\n"
        "## 五、修正建议（按优先级排列）"
    ),
))

register(WorkflowDef(
    id="data_check",
    name="数据核查",
    persona="reviewer",
    trigger_patterns=[
        "数据核查", "核查数据", "验证数据", "fact check",
        "数据验证",
    ],
    steps=[
        "读取文档，提取所有关键数字/百分比/日期/公司名/产品名",
        "逐条独立搜索验证：不信原文引用，独立找原始出处",
        "标注每个数据点：✅已验证 / ⚠️部分偏差 / ❌无法验证 / 📅数据过时",
        "输出数据验证清单",
    ],
    tools_hint=["web_search", "web_research", "web_read", "read_doc", "search_docs"],
    output_template=(
        "## 数据验证清单\n"
        "| # | 原文数据 | 验证结果 | 出处 | 判定 |\n"
        "## 致命数据问题（逐条展开❌项）\n"
        "## 陈旧数据（逐条展开📅项）"
    ),
))

register(WorkflowDef(
    id="logic_review",
    name="逻辑拆解",
    persona="reviewer",
    trigger_patterns=[
        "逻辑拆解", "逻辑审查", "找逻辑漏洞", "逻辑问题",
        "因果分析",
    ],
    steps=[
        "读取文档，提取所有因果断言（因此/所以/说明/验证了/证明了）",
        "逐条拆解推论链：前提A + 前提B → 结论C",
        "检验：前提是否成立？结论是否必然？是否有被忽略的前提D？",
        "标注逻辑谬误类型",
        "输出逻辑链拆解报告",
    ],
    tools_hint=["web_search", "read_doc", "search_docs"],
    output_template=(
        "## 推论链拆解\n"
        "### 推论1：{断言}\n"
        "- 前提：...\n- 检验：...\n- 问题：...\n- 谬误类型：...\n"
        "## 逻辑问题汇总（级别/谬误/影响）"
    ),
))

register(WorkflowDef(
    id="feasibility_challenge",
    name="可行性挑战",
    persona="reviewer",
    trigger_patterns=[
        "可行性挑战", "压力测试", "挑战可行性", "challenge",
        "能不能做到",
    ],
    steps=[
        "读取文档中的执行计划/时间线/资源规划",
        "逐项追问：人力(工时)、时间(串行依赖)、资金(单位经济)、竞争(反应)、技术(断供风险)",
        "构造最坏情况场景：核心假设全不成立时亏多少？时间线翻倍现金流能撑吗？",
        "输出可行性追问报告",
    ],
    tools_hint=["web_search", "read_doc", "search_docs"],
    output_template=(
        "## 可行性逐项追问\n"
        "### F1：{挑战}\n"
        "- 级别：\n- 原文计划：\n- 追问：\n- 最坏情况：\n"
        "## 最坏情况总场景\n"
        "## 建议调整"
    ),
))
