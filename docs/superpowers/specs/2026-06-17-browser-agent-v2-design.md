# Browser Agent V2 — 结构化记忆 + 主动压缩 + 检查点

## 背景

现有 `agent.py` 使用扁平笔记 `_agent_notes` 字符串 + LangGraph Plan-then-Execute 架构，
测试效果差，根因：

1. 笔记是扁平文本，写入格式不可控
2. 压缩触发太晚（超过 12000 token 才压缩），上下文已污染多轮推理
3. 压缩时截断过狠（`content[:200]`），关键数据可能丢失
4. 用户无法干预，一路自动跑到结束
5. planner 与 executor 脱节——规划结果只是文本，executor 看不到规划过程

## 决策记录

| 决策点 | 选择 | 理由 |
|--------|------|------|
| LLM | 继续用 DeepSeek | 用上下文工程弥补模型能力 |
| 用户介入程度 | 关键检查点确认 | 规划后确认、采集前确认 |
| 数据提取方式 | 新增 `browser_extract` 工具 | 高级抽象，JS 提取后 LLM 结构化 |
| 输出形式 | 纯文本总结 | 不需要文件输出 |
| 架构方案 | 单 Agent + 结构化记忆 + 主动压缩 | 简单直接，避免双 agent 脱节问题 |

## 文件结构

```
research-flow/
├── cdp/                    # 不动
│   ├── cdp.py              # CDP WebSocket 客户端
│   ├── browser.py          # Browser 操作 API
│   └── tools.py            # LangChain 工具（需新增 browser_extract）
├── agent/
│   ├── __init__.py
│   ├── memory.py            # 结构化记忆（plan / findings / context）
│   ├── compressor.py        # 主动上下文压缩
│   ├── graph.py             # LangGraph 图定义
│   ├── prompts.py           # system prompt 集中管理
│   └── tools.py             # 新工具：update_memory, read_memory
├── config.py               # 不动
├── main.py                 # 新入口
└── agent.py                # 旧版保留不动
```

## 结构化记忆系统

替代现有扁平笔记，分三块独立管理：

### Plan（任务清单）

```python
{
    "goal": "采集100个成都Python岗位并计算平均工资",
    "steps": [
        {"id": 1, "action": "打开boss直聘职位搜索页", "status": "pending", "note": ""},
        {"id": 2, "action": "选择城市为成都",           "status": "pending", "note": ""},
        {"id": 3, "action": "搜索Python岗位",           "status": "pending", "note": ""},
        {"id": 4, "action": "滚动页面采集100条岗位数据", "status": "pending", "note": ""},
        {"id": 5, "action": "计算并汇报平均工资",        "status": "pending", "note": ""},
    ],
    "current_step": 1,
}
```

- `status`: `pending` / `in_progress` / `done` / `failed`
- `note`: 补充说明
- `update_memory("plan", ...)` 写入时自动推进 `current_step`

### Findings（采集数据）

```python
{
    "items": [
        {"岗位": "Python开发工程师", "工资": "10-15K", "地区": "高新区"},
    ],
    "summary": "已采集 97 条岗位数据，覆盖 5 个区",
}
```

- `browser_extract` 提取的数据自动 append 到 `items`
- `summary` 每次写入时由 LLM 更新
- **数据不进入对话历史**，只存在 findings 里

### Context（当前状态）

```python
{
    "current_url": "https://www.zhipin.com/web/geek/jobs?query=Python&city=101270100",
    "current_action": "正在滚动页面采集岗位数据",
    "last_result": "snapshot 发现 20 个交互元素，页面底部有加载更多按钮",
    "errors": ["@e5 引用失效，已重新 snapshot"],
}
```

- 每次工具调用后由 compressor 自动更新
- 只保留最新一条，不积累
- `errors` 最多保留最近 3 条

### 注入格式

注入到 system prompt **尾部**（Transformer 对尾部也敏感）：

```
[计划] 采集100个成都Python岗位并计算平均工资
  ✓ 1. 打开boss直聘职位搜索页
  → 2. 选择城市为成都          ← 当前步骤
  · 3. 搜索Python岗位
  · 4. 滚动页面采集100条岗位数据
  · 5. 计算并汇报平均工资

[数据] 已采集 0/100 条。暂无数据。

[状态] 在 about:blank | 刚打开浏览器
```

## 主动上下文压缩

### 核心原则：数据进 findings，历史进摘要

每次工具调用返回后，compressor 在下一次 LLM 调用前做三件事：

**1. 提取数据 → findings**

`browser_extract` 返回的结构化数据直接 append 到 `findings.items`，ToolMessage 里只保留简短确认。

**2. 压缩工具返回 → context**

每次工具调用后，用 LLM 将 ToolMessage 压缩为一句摘要：

| 工具调用 | 压缩结果示例 |
|---------|-------------|
| `browser_open(url)` | `"已打开 zhipin.com 职位搜索页"` |
| `browser_snapshot()` | `"页面有81个交互元素：搜索框@e1、城市筛选@e3...底部有加载更多@e78"` |
| `browser_click(@e5)` | `"点击了第1个职位，进入详情页"` |
| `browser_scroll(down, 300)` | `"向下滚动300px，出现新岗位列表"` |
| `browser_extract(...)` | `"提取了20条岗位数据（工资10-20K），已存入 findings"` |

**实现：** LangGraph 的 ToolNode 后面加 `compress` 节点，替换原始 ToolMessage 为压缩摘要。

**3. 丢弃老消息**

对话历史超过 `MAX_MESSAGES` 条时，从头部丢弃，但永远保留：
- SystemMessage（第1条）
- 用户原始输入（第1条 HumanMessage）
- 最近 6 条消息

关键数据已在 findings 里，丢掉的历史无需摘要。

### 压缩触发时序

```
User → [HumanMsg] → Agent → [tool_call] → Tools → raw_result
                                                        ↓
                                                  compress node
                                                        ↓
                                               compressed ToolMsg
                                                        ↓
                                         inject memory into system prompt
                                                        ↓
                                                     Agent → ...
```

### 关键参数

```python
MAX_MESSAGES = 40
COMPRESS_EVERY_TURN = True
KEEP_RECENT = 6
```

## 工具设计

### 保留的浏览器工具（来自 cdp/tools.py）

- browser_open, browser_snapshot, browser_click, browser_fill, browser_type
- browser_scroll, browser_scroll_to_bottom, browser_scroll_into_view
- browser_title, browser_current_url, browser_wait, browser_close

### 新增工具

**update_memory(section, data)** — 写入结构化记忆

- `section`: `"plan"` | `"findings"` | `"context"`
- `data`: JSON 字符串
- plan: 合并更新，未传字段保留原值
- findings: items 追加，summary 替换
- context: 整体替换（agent 通常不手动更新 context，由 compressor 自动管理）

**read_memory()** — 读取全部记忆

返回格式化文本（同注入 system prompt 尾部的格式）

**browser_extract(instruction)** — 从页面提取结构化数据

- `instruction`: 提取指令，如 `"提取所有岗位的名称、工资、地区"`
- 行为：
  1. 调用 `Accessibility.getFullAXTree` 获取完整可访问性树
  2. LLM 根据 instruction 从树中提取结构化数据
  3. 返回 JSON 数组
  4. 自动 append 到 `findings.items`
  5. ToolMessage 只返回简短确认（如 `"提取了20条数据，已存入 findings"`）

### 移除的工具

- `write_note` / `read_note`（被 `update_memory` / `read_memory` 替代）

## LangGraph 图结构

```
START → planner → confirm → agent → [路由]
                                ↑        /    |    \
                                └── combine  limit   END
                                     ↓
                                  compressor
                                     ↓
                                   tools ────┘
```

**节点说明：**

- `planner`: 分析用户意图，调用 `update_memory("plan", ...)` 生成结构化计划
- `confirm`: **interrupt_before**，暂停等用户确认计划
- `agent`: LLM 推理节点，决定下一步操作
- `combine`: 合并工具结果，准备压缩
- `compressor`: 压缩 ToolMessage，更新 context
- `tools`: 执行工具调用

**路由逻辑：**

- `agent` 有 `tool_calls` → `combine`
- `agent` 纯文本（无 `tool_calls`）→ `END`
- 步数/错误超限 → `limit` → `END`

## Human-in-the-loop 检查点

使用 LangGraph `interrupt_before` 在 `confirm` 节点暂停。

**流程：**
1. planner 生成计划，调用 `update_memory("plan", ...)`
2. 到达 confirm 节点，图暂停
3. main.py 展示计划给用户
4. 用户输入：确认 / 修改 / 取消
5. 确认后 `Command(resume="confirmed")` 继续
6. 进入 agent 执行循环

**交互示例：**
```
你: 打开boss直聘，采集100个成都Python岗位平均工资

📋 计划已生成：
  1. 打开 boss直聘职位搜索页
  2. 选择城市为成都
  3. 搜索 Python 岗位
  4. 滚动页面采集 100 条岗位数据
  5. 计算并汇报平均工资

确认执行？(y/修改/取消): y

🔧 browser_open("https://www.zhipin.com/web/geek/jobs")
   → 已打开 zhipin.com
...

📊 采集完成：共97条数据
   平均工资：12.8K | 中位数：12K | 范围：6-35K

Agent: 成都Python岗位共采集97条，平均工资12.8K...
```

## System Prompt 设计（prompts.py）

集中管理，分三段：

1. **身份与核心规则** — "你是浏览器操作 Agent，严格按计划步骤执行"
2. **操作要点** — snapshot 优先、一次一步、引用格式
3. **记忆注入区** — 动态拼入 plan / findings / context

关键策略：在 prompt 中明确要求 agent "完成一步后立即 `update_memory` 更新状态"，
"数据用 `browser_extract` 提取，不要手动复制到对话中"。

## 不做的事

- 不修改现有 `agent.py`、`boss_fktest_*.py` 等文件
- 不实现文件输出（CSV/JSON），只做纯文本总结
- 不切换 LLM，继续用 DeepSeek
- 不添加 `browser_evaluate`（已有但注释掉的工具），用 `browser_extract` 替代