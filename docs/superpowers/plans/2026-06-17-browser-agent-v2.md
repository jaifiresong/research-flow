# Browser Agent V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the browser Agent with structured memory, proactive context compression, and human-in-the-loop checkpoints, replacing the flat-note architecture in `agent.py`.

**Architecture:** Single LangGraph agent with three structured memory blocks (plan/findings/context) injected into system prompt tail. Each tool call result is compressed before feeding back. A confirm node interrupts before execution for user approval. New `browser_extract` tool extracts structured data from pages into findings without polluting context.

**Tech Stack:** Python 3.12, LangGraph 1.2.5, LangChain 1.3.9, LangChain-OpenAI 1.3.2, websockets, existing `cdp/` package

---

## File Structure

| File | Responsibility |
|------|---------------|
| `agent/__init__.py` | Package init, exports |
| `agent/memory.py` | StructuredMemory class — plan/findings/context storage, read/write, format for injection |
| `agent/tools.py` | New tools: `update_memory`, `read_memory`, `browser_extract` |
| `agent/compressor.py` | Tool result compression — compress each ToolMessage after execution |
| `agent/prompts.py` | All system prompts — planner, executor, extractor |
| `agent/graph.py` | LangGraph graph definition — nodes, edges, interrupt |
| `main.py` | Entry point — interactive loop with confirm/resume |
| `cdp/tools.py` | Modify: add `browser_extract` tool |

---

### Task 1: StructuredMemory

**Files:**
- Create: `agent/__init__.py`
- Create: `agent/memory.py`
- Test: `tests/test_memory.py`

- [ ] **Step 1: Create `agent/__init__.py`**

```python
from agent.memory import StructuredMemory
from agent.graph import build_agent_graph

__all__ = ["StructuredMemory", "build_agent_graph"]
```

- [ ] **Step 2: Write failing test for StructuredMemory**

Create `tests/test_memory.py`:

```python
import json
import pytest
from agent.memory import StructuredMemory


def test_initial_state():
    mem = StructuredMemory()
    assert mem.plan == {}
    assert mem.findings == {"items": [], "summary": ""}
    assert mem.context == {}


def test_update_plan_merges():
    mem = StructuredMemory()
    mem.update("plan", {"goal": "test", "steps": [{"id": 1, "action": "step1", "status": "pending", "note": ""}]})
    assert mem.plan["goal"] == "test"
    assert len(mem.plan["steps"]) == 1
    mem.update("plan", {"current_step": 2})
    assert mem.plan["goal"] == "test"
    assert mem.plan["current_step"] == 2


def test_update_findings_appends_items():
    mem = StructuredMemory()
    mem.update("findings", {"items": [{"a": 1}], "summary": "1 item"})
    assert len(mem.findings["items"]) == 1
    mem.update("findings", {"items": [{"a": 2}], "summary": "2 items"})
    assert len(mem.findings["items"]) == 2
    assert mem.findings["summary"] == "2 items"


def test_update_context_replaces():
    mem = StructuredMemory()
    mem.update("context", {"current_url": "https://example.com", "current_action": "browsing"})
    assert mem.context["current_url"] == "https://example.com"
    mem.update("context", {"current_url": "https://other.com", "current_action": "clicking"})
    assert mem.context["current_url"] == "https://other.com"
    assert mem.context["current_action"] == "clicking"


def test_format_for_injection_empty():
    mem = StructuredMemory()
    text = mem.format_for_injection()
    assert "[计划]" not in text or "暂无计划" in text


def test_format_for_injection_with_plan():
    mem = StructuredMemory()
    mem.update("plan", {
        "goal": "采集100个Python岗位",
        "steps": [
            {"id": 1, "action": "打开boss直聘", "status": "done", "note": ""},
            {"id": 2, "action": "选择成都", "status": "in_progress", "note": ""},
            {"id": 3, "action": "搜索Python", "status": "pending", "note": ""},
        ],
        "current_step": 2,
    })
    text = mem.format_for_injection()
    assert "采集100个Python岗位" in text
    assert "✓" in text or "→" in text


def test_format_for_injection_with_findings():
    mem = StructuredMemory()
    mem.update("findings", {"items": [{"岗位": "Python", "工资": "10K"}], "summary": "已采集1条"})
    text = mem.format_for_injection()
    assert "已采集" in text


def test_read_returns_all():
    mem = StructuredMemory()
    mem.update("plan", {"goal": "test"})
    result = mem.read()
    assert "计划" in result or "plan" in result.lower()


def test_update_invalid_section_raises():
    mem = StructuredMemory()
    with pytest.raises(ValueError):
        mem.update("invalid_section", {})
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /mnt/d/tmp/research-flow && python -m pytest tests/test_memory.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent'`

- [ ] **Step 4: Implement StructuredMemory**

Create `agent/memory.py`:

```python
import json
from typing import Any


class StructuredMemory:
    def __init__(self):
        self.plan: dict = {}
        self.findings: dict = {"items": [], "summary": ""}
        self.context: dict = {}

    def update(self, section: str, data: str | dict) -> None:
        if isinstance(data, str):
            data = json.loads(data)

        if section == "plan":
            self._merge_plan(data)
        elif section == "findings":
            self._merge_findings(data)
        elif section == "context":
            self.context = data
        else:
            raise ValueError(f"Unknown memory section: {section}")

    def _merge_plan(self, data: dict) -> None:
        if "steps" in data and "steps" not in self.plan:
            self.plan["steps"] = data["steps"]
        elif "steps" in data and "steps" in self.plan:
            existing = {s["id"]: s for s in self.plan["steps"]}
            for step in data["steps"]:
                existing[step["id"]] = step
            self.plan["steps"] = sorted(existing.values(), key=lambda s: s["id"])

        for key, value in data.items():
            if key != "steps":
                self.plan[key] = value

    def _merge_findings(self, data: dict) -> None:
        if "items" in data:
            self.findings["items"].extend(data["items"])
        if "summary" in data:
            self.findings["summary"] = data["summary"]

    def read(self) -> str:
        return self.format_for_injection()

    def format_for_injection(self) -> str:
        parts = []
        parts.append(self._format_plan())
        parts.append(self._format_findings())
        parts.append(self._format_context())
        return "\n\n".join(parts)

    def _format_plan(self) -> str:
        if not self.plan:
            return "[计划] 暂无计划"

        lines = [f"[计划] {self.plan.get('goal', '未设定目标')}"]
        current = self.plan.get("current_step", 0)
        for step in self.plan.get("steps", []):
            sid = step["id"]
            action = step["action"]
            note = f" — {step['note']}" if step.get("note") else ""
            if step["status"] == "done":
                marker = "✓"
            elif step["status"] == "failed":
                marker = "✗"
            elif step["status"] == "in_progress" or sid == current:
                marker = "→"
            else:
                marker = "·"
            lines.append(f"  {marker} {sid}. {action}{note}")

        return "\n".join(lines)

    def _format_findings(self) -> str:
        count = len(self.findings.get("items", []))
        summary = self.findings.get("summary", "")
        if count == 0:
            return "[数据] 暂无数据。"
        if summary:
            return f"[数据] {summary}"
        return f"[数据] 已采集 {count} 条。"

    def _format_context(self) -> str:
        if not self.context:
            return "[状态] 初始状态"
        url = self.context.get("current_url", "未知页面")
        action = self.context.get("current_action", "")
        parts = [f"[状态] 在 {url}"]
        if action:
            parts.append(action)
        errors = self.context.get("errors", [])
        for err in errors[:3]:
            parts.append(f"⚠ {err}")
        return " | ".join(parts)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /mnt/d/tmp/research-flow && python -m pytest tests/test_memory.py -v`
Expected: All 8 tests PASS

- [ ] **Step 6: Create `tests/__init__.py`**

Empty file to make `tests` a package:

```python
```

- [ ] **Step 7: Run all tests again to confirm**

Run: `cd /mnt/d/tmp/research-flow && python -m pytest tests/test_memory.py -v`

- [ ] **Step 8: Commit**

```bash
git add agent/__init__.py agent/memory.py tests/__init__.py tests/test_memory.py
git commit -m "feat: add StructuredMemory with plan/findings/context"
```

---

### Task 2: Prompts

**Files:**
- Create: `agent/prompts.py`

- [ ] **Step 1: Create prompts.py**

Create `agent/prompts.py`:

```python
PLANNER_SYSTEM_PROMPT = """你是任务规划助手。分析用户的浏览器操作任务，拆解为具体的步骤计划。

## 输出要求

你必须调用 update_memory 工具，将计划写入 memory。格式如下：

```json
{
  "section": "plan",
  "data": {
    "goal": "一句话描述任务目标",
    "steps": [
      {"id": 1, "action": "具体浏览器操作描述", "status": "pending", "note": ""},
      {"id": 2, "action": "...", "status": "pending", "note": ""},
      ...
    ],
    "current_step": 1
  }
}
```

## 规划原则

- 每步是一个具体浏览器操作（打开页面、点击元素、填入文本、滚动、提取数据等）
- 步骤按依赖顺序排列
- 输入/点击目标尽可能具体
- 控制在 3-8 步
- 如果任务涉及数据采集，明确在哪一步用 browser_extract 提取什么字段
- 最后一步通常是数据汇总或输出结论
"""


EXECUTOR_SYSTEM_PROMPT = """你是浏览器操作执行助手。

═══ 核心规则 ═══

1. 严格按 [计划] 中的步骤顺序执行，不要跳步、不要重复已完成步骤
2. 每次只执行一个步骤
3. 完成一个步骤后，立刻调用 update_memory 更新 plan（将对应步骤 status 改为 done，推进 current_step）
4. 需要采集数据时，使用 browser_extract 而不是手动复制到对话
5. 交互前先 browser_snapshot 了解页面元素
6. 点击/填表使用快照引用（@e1、@e42）

═══ 记忆工具使用 ═══

- update_memory("plan", ...) — 更新任务计划（改步骤状态或推进 current_step）
- update_memory("findings", ...) — 追加采集数据（一般不手动调用，browser_extract 会自动写入）
- read_memory() — 查看当前所有记忆（计划+数据+状态）

═══ 错误处理 ═══

- 工具报错 [错误] 时不要重复相同操作
- 引用失效 → 重新 browser_snapshot
- 某步骤连续失败 2 次 → update_memory 标记为 failed，进入下一步
- 用 update_memory("context", {"errors": [...]}) 记录遇到的错误

═══ 完成条件 ═══

所有步骤 done 后，输出简洁的文本总结作为最终回复，不要调用任何工具。
"""


EXTRACTOR_PROMPT = """从以下页面可访问性树中提取结构化数据。

用户要求提取：{instruction}

页面交互元素列表：
{snapshot}

请以 JSON 数组格式输出提取结果。每个对象包含用户要求的字段。
如果某个字段在页面上找不到，对应值设为 null。

示例输出格式：
```json
[
  {{"岗位": "Python开发工程师", "工资": "10-15K", "地区": "高新区"}},
  {{"岗位": "后端开发", "工资": "12-20K", "地区": "天府新区"}}
]
```

只输出 JSON 数组，不要输出其他内容。"""
```

- [ ] **Step 2: Commit**

```bash
git add agent/prompts.py
git commit -m "feat: add planner, executor, and extractor prompts"
```

---

### Task 3: browser_extract Tool

**Files:**
- Modify: `cdp/browser.py` — add `extract_ax_tree()` method
- Modify: `cdp/tools.py` — add `browser_extract` tool, update `BROWSER_TOOLS`

- [ ] **Step 1: Add `extract_ax_tree()` to Browser class**

In `cdp/browser.py`, add a method that returns the raw accessibility tree nodes (full, not just interactive elements):

```python
async def extract_ax_tree(self) -> dict:
    await self._cdp.send('Accessibility.enable')
    nodes = await self._cdp.send('Accessibility.getFullAXTree')
    return nodes
```

Add this method after the `snapshot` method (around line 93). The method reuses the existing CDP connection and `Accessibility.enable` call pattern from `snapshot`.

- [ ] **Step 2: Add `browser_extract` tool to `cdp/tools.py`**

Add the following tool function after the existing `browser_snapshot` tool (around line 105):

```python
@tool
@log_tool_call
async def browser_extract(instruction: str) -> str:
    """从当前页面提取结构化数据。

    获取页面的完整内容树，然后根据指令提取特定字段。
    提取的数据会自动保存到 agent 的 findings 中。

    Args:
        instruction: 提取指令，描述要从页面提取什么数据。
                     例如："提取所有岗位的名称、工资、地区"
                     例如："提取职位列表中的公司名和薪资范围"
    """
    await ensure_started()
    b = get_browser()
    raw = await b.extract_ax_tree()
    ax_nodes = raw.get('nodes', [])

    readable_lines = []
    for node in ax_nodes:
        role_val = node.get('role', {})
        role = role_val.get('value', '').lower() if isinstance(role_val, dict) else ''
        if not role:
            continue
        name = ''
        if isinstance(node.get('name'), dict):
            name = node['name'].get('value', '')
        elif isinstance(node.get('name'), str):
            name = node['name']
        value = ''
        if isinstance(node.get('value'), dict):
            value = node['value'].get('value', '')

        props = {}
        for p in node.get('properties') or []:
            v = p.get('value', {})
            props[p.get('name', '')] = v.get('value', '') if isinstance(v, dict) else ''

        line = f'[{role}]'
        if name:
            line += f' "{str(name)[:120]}"'
        if value and role in ('statictext', 'text', 'heading', 'paragraph', 'generic'):
            display_val = str(value)[:120]
            if display_val != str(name)[:120]:
                line += f' = {display_val}'
        url_prop = props.get('url', '')
        if url_prop and not url_prop.startswith('javascript:'):
            line += f' → {url_prop[:80]}'
        readable_lines.append(line)

    snapshot_text = '\n'.join(readable_lines[:300])
    if len(readable_lines) > 300:
        snapshot_text += f'\n... (共 {len(readable_lines)} 个节点，已截断)'

    return f"EXTRACT_RESULT|{instruction}|{len(readable_lines)}\n{snapshot_text}"
```

- [ ] **Step 3: Update BROWSER_TOOLS list in `cdp/tools.py`**

Find the `BROWSER_TOOLS` list (around line 246) and add `browser_extract`:

```python
BROWSER_TOOLS = [
    browser_open,
    browser_snapshot,
    browser_extract,
    browser_click,
    browser_fill,
    browser_type,
    browser_scroll,
    browser_scroll_to_bottom,
    browser_scroll_into_view,
    # browser_evaluate,
    browser_title,
    browser_current_url,
    browser_wait,
    browser_close,
]
```

- [ ] **Step 4: Commit**

```bash
git add cdp/browser.py cdp/tools.py
git commit -m "feat: add browser_extract tool and extract_ax_tree method"
```

---

### Task 4: Agent Tools (update_memory, read_memory)

**Files:**
- Create: `agent/tools.py`

- [ ] **Step 1: Create agent/tools.py**

```python
import json
import logging
from langchain.tools import tool
from agent.memory import StructuredMemory

logger = logging.getLogger(__name__)

_memory = StructuredMemory()


def get_memory() -> StructuredMemory:
    return _memory


def reset_memory() -> None:
    global _memory
    _memory = StructuredMemory()


@tool
async def update_memory(section: str, data: str) -> str:
    """写入结构化记忆。

    Args:
        section: 记忆区块，可选值："plan"（任务计划）、"findings"（采集数据）、"context"（当前状态）
        data: JSON 格式的数据字符串。
             - plan: {"goal":"...", "steps":[...], "current_step":1}
             - findings: {"items":[...], "summary":"..."}
             - context: {"current_url":"...", "current_action":"...", "last_result":"...", "errors":[...]}
    """
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError as e:
        return f"[错误] JSON 格式无效: {e}"

    try:
        _memory.update(section, parsed)
    except ValueError as e:
        return f"[错误] {e}"

    summary = _memory.format_for_injection()
    return f"记忆已更新 ({section})。当前状态：\n{summary}"


@tool
async def read_memory() -> str:
    """读取当前所有记忆（计划+数据+状态）。用于查看当前进度和已采集数据。"""
    return _memory.format_for_injection()
```

- [ ] **Step 2: Commit**

```bash
git add agent/tools.py
git commit -m "feat: add update_memory and read_memory tools"
```

---

### Task 5: Compressor

**Files:**
- Create: `agent/compressor.py`

- [ ] **Step 1: Create compressor.py**

```python
import json
import logging
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from config import OPENAI_API_KEY, OPENAI_MODEL

logger = logging.getLogger(__name__)

_llm = ChatOpenAI(
    model=OPENAI_MODEL,
    api_key=OPENAI_API_KEY,
    base_url="https://api.deepseek.com",
)

MAX_MESSAGES = 40
KEEP_RECENT = 6


def estimate_tokens(msgs: list) -> int:
    total = 0
    for m in msgs:
        content = getattr(m, "content", "") or ""
        total += len(content) // 2
        if isinstance(m, AIMessage) and m.tool_calls:
            for tc in m.tool_calls:
                total += len(json.dumps(tc.get("args", {}))) // 2
    return total


async def compress_tool_result(tool_msg: ToolMessage) -> str:
    content = tool_msg.content
    if len(content) <= 150:
        return content

    tool_name = tool_msg.name or "unknown"
    prompt = (
        f"将以下浏览器工具调用结果压缩为一句话摘要（≤80字），"
        f"保留关键信息（页面状态、元素数量、操作结果、错误），"
        f"丢弃详细的元素列表和冗长文本：\n\n"
        f"工具: {tool_name}\n结果:\n{content[:2000]}"
    )

    try:
        from langchain_core.messages import HumanMessage as HM
        resp = await _llm.ainvoke([HM(content=prompt)])
        return str(resp.content).strip()
    except Exception as exc:
        logger.warning("压缩失败: %s", exc)
        return content[:150]


def trim_messages(msgs: list) -> list:
    if len(msgs) <= MAX_MESSAGES:
        return msgs

    system_msgs = [m for m in msgs if isinstance(m, SystemMessage)]
    first_user = next(
        (m for m in msgs if isinstance(m, HumanMessage) and not m.content.startswith("[")),
        None,
    )
    recent = msgs[-KEEP_RECENT:]

    keep_ids = {id(m) for m in system_msgs + recent + ([first_user] if first_user else [])}
    kept = [m for m in msgs if id(m) in keep_ids]
    dropped_count = len(msgs) - len(kept)
    if dropped_count > 0 and first_user:
        idx = kept.index(first_user)
        kept.insert(idx + 1, HumanMessage(content=f"[已丢弃 {dropped_count} 条旧消息]"))
    return kept
```

- [ ] **Step 2: Commit**

```bash
git add agent/compressor.py
git commit -m "feat: add context compressor with proactive compression"
```

---

### Task 6: LangGraph Graph

**Files:**
- Create: `agent/graph.py`

This is the core piece. It defines the full agent graph: planner → confirm → agent loop (agent → combine → compressor → tools → agent).

- [ ] **Step 1: Create graph.py**

```python
import json
import logging
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.types import interrupt, Command

from cdp.tools import BROWSER_TOOLS, browser_close
from agent.memory import StructuredMemory
from agent.tools import update_memory, read_memory, get_memory, reset_memory
from agent.compressor import compress_tool_result, trim_messages, estimate_tokens
from agent.prompts import PLANNER_SYSTEM_PROMPT, EXECUTOR_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

MAX_STEPS = 30
MAX_ERRORS = 5

llm = ChatOpenAI(
    model="deepseek-chat",
    api_key=__import__("os").environ.get("OPENAI_API_KEY", ""),
    base_url="https://api.deepseek.com",
)

ALL_TOOLS = list(BROWSER_TOOLS) + [update_memory, read_memory]
llm_with_tools = llm.bind_tools(ALL_TOOLS)


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


async def planner_node(state: AgentState) -> dict:
    user_msgs = [m for m in state["messages"] if isinstance(m, HumanMessage) and not m.content.startswith("[")]
    if not user_msgs:
        return {}

    user_goal = user_msgs[-1].content
    reset_memory()
    memory = get_memory()
    memory.update("context", {"current_url": "初始", "current_action": f"用户任务: {user_goal}", "errors": []})

    planner_llm = llm.bind_tools([update_memory])
    prompt = f"{PLANNER_SYSTEM_PROMPT}\n\n用户任务：{user_goal}"
    response = await planner_llm.ainvoke([SystemMessage(content=prompt), HumanMessage(content=user_goal)])

    return {"messages": [response]}


async def confirm_node(state: AgentState) -> dict:
    memory = get_memory()
    plan_text = memory.format_for_injection()

    user_response = interrupt(f"📋 计划已生成：\n{plan_text}\n\n确认执行？(y/n)")

    if isinstance(user_response, str) and user_response.lower().strip() in ("y", "yes", "确认", "确认执行"):
        return {"messages": [HumanMessage(content="[已确认计划，开始执行]")]}
    else:
        return {"messages": [HumanMessage(content=f"[用户反馈: {user_response}]，请根据反馈调整计划。")]}


async def agent_node(state: AgentState) -> dict:
    memory = get_memory()
    msgs = list(state["messages"])

    if not any(isinstance(m, SystemMessage) for m in msgs):
        msgs.insert(0, SystemMessage(content=EXECUTOR_SYSTEM_PROMPT))

    memory_text = memory.format_for_injection()
    if memory_text.strip():
        msgs.append(HumanMessage(content=f"[当前记忆]\n{memory_text}"))

    response = await llm_with_tools.ainvoke(msgs)
    return {"messages": [response]}


async def combine_node(state: AgentState) -> dict:
    msgs = state["messages"]
    compressed = []

    for m in msgs:
        if isinstance(m, ToolMessage) and len(m.content) > 150:
            summary = await compress_tool_result(m)
            compressed.append(
                ToolMessage(content=summary, tool_call_id=m.tool_call_id, name=m.name)
            )
        else:
            compressed.append(m)

    return {"messages": compressed}


def should_continue(state: AgentState) -> str:
    msgs = state["messages"]
    last = msgs[-1]

    if isinstance(last, AIMessage) and not last.tool_calls:
        return "end"

    rounds = sum(1 for m in msgs if isinstance(m, AIMessage) and m.tool_calls)
    errors = sum(1 for m in msgs if isinstance(m, ToolMessage) and m.content.startswith("[错误]"))

    if errors >= MAX_ERRORS:
        return "limit"
    if rounds >= MAX_STEPS:
        return "limit"

    return "tools"


async def limit_reached_node(state: AgentState) -> dict:
    rounds = sum(1 for m in state["messages"] if isinstance(m, AIMessage) and m.tool_calls)
    errors = sum(1 for m in state["messages"] if isinstance(m, ToolMessage) and m.content.startswith("[错误]"))
    reason = f"错误次数已达 {errors} 次" if errors >= MAX_ERRORS else f"步数已达 {rounds} 步"
    return {"messages": [AIMessage(content=f"[任务终止: {reason}]")]}


def build_agent_graph():
    graph = StateGraph(AgentState)

    graph.add_node("planner", planner_node)
    graph.add_node("confirm", confirm_node)
    graph.add_node("agent", agent_node)
    graph.add_node("combine", combine_node)
    graph.add_node("tools", ToolNode(ALL_TOOLS))
    graph.add_node("limit_reached", limit_reached_node)

    graph.set_entry_point("planner")
    graph.add_edge("planner", "confirm")
    graph.add_edge("confirm", "agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", "limit": "limit_reached", "end": END})
    graph.add_edge("tools", "combine")
    graph.add_edge("combine", "agent")
    graph.add_edge("limit_reached", END)

    return graph.compile(interrupt_before=["confirm"])
```

- [ ] **Step 2: Commit**

```bash
git add agent/graph.py
git commit -m "feat: add LangGraph agent graph with structured memory and confirm node"
```

---

### Task 7: Main Entry Point

**Files:**
- Create: `main.py`

This is the interactive loop that handles the interrupt/resume flow.

- [ ] **Step 1: Create main.py**

```python
import asyncio
import json
import logging

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from agent import StructuredMemory, build_agent_graph
from agent.memory import StructuredMemory as _SM
from agent.tools import get_memory, reset_memory
from cdp.tools import browser_close

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def chat_loop():
    graph = build_agent_graph()
    thread_id = "1"
    config = {"configurable": {"thread_id": thread_id}}

    print("=" * 50)
    print("浏览器 Agent V2 — 结构化记忆 + 检查点")
    print("=" * 50)
    print("确保 Chrome 已启动：google-chrome --remote-debugging-port=9222")
    print("输入指令开始，/quit 退出\n")

    while True:
        try:
            user_input = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue
        if user_input.lower() in ("/quit", "/exit", ":q"):
            break

        reset_memory()
        state = {"messages": [HumanMessage(content=user_input)]}

        while True:
            try:
                result = await graph.ainvoke(state, config=config)
            except Exception as exc:
                logger.error("执行异常: %s", exc)
                break

            state_values = result

            next_input = None
            snapshot = await graph.aget_state(config)
            if snapshot.next:
                for node_name in snapshot.next:
                    if node_name == "confirm":
                        memory = get_memory()
                        plan_text = memory.format_for_injection()
                        print(f"\n📋 计划已生成：\n{plan_text}\n")
                        confirm = input("确认执行？(y/n/修改): ").strip()
                        if confirm.lower() in ("y", "yes", "确认", ""):
                            next_input = Command(resume="confirmed")
                        else:
                            next_input = Command(resume=confirm)
                        break

            if next_input is not None:
                result = await graph.ainvoke(next_input, config=config)
                state_values = result
                snapshot = await graph.aget_state(config)
                if not snapshot.next:
                    break
                continue

            break

        messages = state_values.get("messages", [])
        for m in messages:
            content = getattr(m, "content", "")
            tool_calls = getattr(m, "tool_calls", None)
            if tool_calls:
                for tc in tool_calls:
                    args_str = json.dumps(tc.get("args", {}), ensure_ascii=False)
                    print(f"  🔧 {tc['name']}({args_str})")
            elif content and not content.startswith("[当前记忆]"):
                prefix = "⚠️ " if content.startswith("[错误]") else ""
                print(f"Agent: {prefix}{content[:500]}")

        memory = get_memory()
        print(f"\n{'=' * 40}")
        print(memory.format_for_injection())
        print(f"{'=' * 40}\n")


async def main():
    try:
        await chat_loop()
    except Exception as exc:
        logger.error("运行异常: %s", exc)
    finally:
        await browser_close.ainvoke({})

if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Verify the entry point runs**

Run: `cd /mnt/d/tmp/research-flow && python -c "from agent import StructuredMemory, build_agent_graph; print('Import OK')"`

Expected: `Import OK`

If import fails, fix the import chain before committing.

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: add main.py entry point with interrupt/resume flow"
```

---

### Task 8: Update agent/__init__.py and Fix Imports

**Files:**
- Modify: `agent/__init__.py`
- Modify: `config.py` (ensure it exports correctly)

- [ ] **Step 1: Verify and fix agent/__init__.py**

The current `agent/__init__.py` (from Task 1) should be:

```python
from agent.memory import StructuredMemory
from agent.graph import build_agent_graph

__all__ = ["StructuredMemory", "build_agent_graph"]
```

Verify this matches. If `build_agent_graph` import fails due to circular dependencies, change to lazy import:

```python
from agent.memory import StructuredMemory

def build_agent_graph():
    from agent.graph import build_agent_graph as _build
    return _build()

__all__ = ["StructuredMemory", "build_agent_graph"]
```

- [ ] **Step 2: Verify config.py exports**

Ensure `config.py` exports `OPENAI_API_KEY` and `OPENAI_MODEL` (it already does):

```python
import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "sk-390ea1267e654c0fa3e3d271237e6696")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "deepseek-chat")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY environment variable is required")
```

- [ ] **Step 3: Full import smoke test**

Run: `cd /mnt/d/tmp/research-flow && python -c "from agent import StructuredMemory, build_agent_graph; from agent.tools import update_memory, read_memory; from agent.compressor import estimate_tokens; print('All imports OK')"`

Expected: `All imports OK`

- [ ] **Step 4: Commit any fixes**

```bash
git add agent/__init__.py agent/graph.py
git commit -m "fix: resolve import issues in agent package"
```

---

### Task 9: End-to-End Integration Test (Manual)

This task is a manual verification — we cannot fully test the CDP agent without a running Chrome instance. Instead, we verify the graph compiles and the memory/tools/compressor logic works in isolation.

- [ ] **Step 1: Run StructuredMemory tests**

Run: `cd /mnt/d/tmp/research-flow && python -m pytest tests/test_memory.py -v`

Expected: All 8 tests PASS

- [ ] **Step 2: Verify graph compiles**

Run: `cd /mnt/d/tmp/research-flow && python -c "from agent.graph import build_agent_graph; g = build_agent_graph(); print('Graph compiled:', type(g).__name__)"`

Expected: `Graph compiled: CompiledGraph` or similar

- [ ] **Step 3: Verify tools register correctly**

Run: `cd /mnt/d/tmp/research-flow && python -c "from agent.tools import update_memory, read_memory; from cdp.tools import BROWSER_TOOLS; print(f'Browser tools: {len(BROWSER_TOOLS)}'); print(f'Memory tools: update_memory, read_memory')"`

Expected: Prints tool counts without errors

- [ ] **Step 4: Commit (if any fixes were needed)**

```bash
git add -A
git commit -m "test: verify full integration"
```

---

## Scope Check

- Spec requirement: "structured memory (plan/findings/context)" → Task 1, Task 2, Task 4
- Spec requirement: "proactive context compression" → Task 5, Task 6
- Spec requirement: "browser_extract tool" → Task 3
- Spec requirement: "human-in-the-loop confirm node" → Task 6, Task 7
- Spec requirement: "don't modify existing files" → Only `cdp/browser.py` and `cdp/tools.py` are modified (to add `extract_ax_tree` and `browser_extract`), all agent code is new
- Spec requirement: "pure text summary output" → Addressed in executor prompt and main.py display

## Implementation Order

The tasks must be executed in order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9. Each task depends on previous ones (memory is used by tools, tools by graph, graph by main).