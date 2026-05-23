# larkBot 测试用例

## 测试前准备

```bash
make install           # 安装依赖
make test-llm          # 验证 LLM 连通性
python3 test_agent.py --dry  # 验证模块逻辑（不需要 API）
```

---

## 本地测试（不经飞书）

```bash
# 交互模式 — 选择用例或输入自定义消息
python3 test_agent.py

# 直接运行某个用例
python3 test_agent.py --case 3    # 市场分析

# 自定义消息（使用当前 persona）
python3 test_agent.py "帮我搜索最近 AI 领域的融资事件"

# 仅测试工作流匹配（秒出结果）
python3 test_agent.py --dry
```

---

## 飞书实际测试用例

启动 bot 后（`make start`），在飞书私聊中发送以下消息：

### Case 1: 简单问答（无工作流）
```
你好，你是谁？
```
**预期**: 以「管家」身份回复，不触发工具调用

### Case 2: 每日早报（assistant）
```
今天有什么安排
```
**预期**: 触发 `daily_briefing` 工作流，调用 `get_agenda` + `get_my_tasks`，显示进度

### Case 3: 会议纪要（assistant）
```
帮我整理今天的会议纪要
```
**预期**: 触发 `meeting_digest`，调用日历 + 会议搜索 + 聊天记录

### Case 4: 市场分析（需先切换角色）
```
/analyst
帮我分析一下 AI Agent 市场
```
**预期**:
- 进度消息: `📋 执行计划 (5-7步)`
- 多轮 `💭 思考` + `📎 搜索网络` 进度
- 最终输出含 TAM/SAM/SOM、PESTLE 等框架结构

### Case 5: 竞品分析（pm）
```
/pm
帮我做一份竞品分析，对比 Notion AI 和 Cursor
```
**预期**: Battlecard 格式输出，含功能矩阵

### Case 6: PRD（pm）
```
帮我写一份 PRD，做一个内部知识库搜索工具
```
**预期**: 8 节 PRD 格式，RICE 排序

### Case 7: 内容策划（ops）
```
/ops
帮我做一个内容策划方案，主题是 AI 编程工具
```
**预期**: AIDA 框架 + 4 周选题日历

### Case 8: 增长方案（ops）
```
我们产品刚上线，帮我设计一个冷启动获客方案
```
**预期**: ICP + Bull's Eye 渠道 + First 100 Customers

### Case 9: 跨角色路由提示
```
/assistant
帮我做一下市场规模测算
```
**预期**: 回复末尾出现 `💡 这类问题切换到 /analyst（市场分析师）可能效果更好`

### Case 10: 飞书链接读取
```
帮我看看这个文档写了什么 https://wvixbzgc0u7.feishu.cn/docx/xxxxxx
```
**预期**: 调用 `read_doc` 而非 `web_search`

### Case 11: 记忆召回
```
我们之前讨论过什么？
```
**预期**: 调用 `recall_memory` 搜索历史

---

## 验证清单

| 功能 | 验证项 | 通过 |
|------|--------|------|
| 工作流匹配 | `--dry` 全通过 | □ |
| System Prompt | 含 persona + frameworks + workflow | □ |
| 进度消息 | 💭 + 📎 正确显示，3 秒节流 | □ |
| 执行计划 | 📋 在多步任务前展示 | □ |
| 角色切换 | `/pm` `/analyst` `/ops` 生效 | □ |
| 路由提示 | 跨域问题提示切换 | □ |
| 熔断器 | 工具连续失败后提示换方式 | □ |
| 记忆 | recall_memory 搜索正常 | □ |
| 飞书链接 | 用 read_doc 不用 web_search | □ |
| 错误恢复 | 超时/限流有友好提示 | □ |
