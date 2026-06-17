"""浏览器 Agent —— Plan-then-Execute 架构：规划节点 + 执行循环 + 记忆管理。"""
import asyncio
import json
import logging
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain.tools import tool
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from cdp.tools import BROWSER_TOOLS, browser_close
from config import OPENAI_API_KEY, OPENAI_MODEL

logger = logging.getLogger(__name__)

# ── 配置 ──

llm = ChatOpenAI(
    model=OPENAI_MODEL,
    api_key=OPENAI_API_KEY,
    base_url="https://api.deepseek.com",
)

_summarize_llm = llm

MAX_STEPS = 12          # 单轮最多工具调用步数
MAX_ERRORS = 3          # 最多错误次数
MAX_MESSAGES = 40       # 多轮对话保留消息数
MAX_CONTEXT_TOKENS = 12000
KEEP_RECENT = 6         # 压缩时保留最近消息数
ENABLE_PLANNING = True   # 是否启用规划节点

# ── 笔记锚定系统 ──

_agent_notes: str = ""
_user_goal: str = ""


@tool
async def write_note(content: str) -> str:
    """写入工作笔记（覆盖模式）。用于更新任务清单进度。

每完成一步，将对应的 [ ] 改为 [x]；遇到阻塞改为 [-]。
写完后整个笔记会持续注入到上下文首部，确保模型不丢失目标。

Args:
    content: 完整的笔记内容，会替换之前的笔记。
"""
    global _agent_notes
    _agent_notes = content
    return f"笔记已保存 ({len(content)} 字)"


@tool
async def read_note() -> str:
    """读取当前工作笔记，查看计划与进度。"""
    return _agent_notes if _agent_notes else "(暂无笔记)"


AGENT_TOOLS = list(BROWSER_TOOLS) + [write_note, read_note]


def _inject_notes(msgs: list) -> list:
    """将用户目标和工作笔记注入上下文首部。

    Transformer 对序列首部注意力权重高，确保目标始终优先。
    """
    if not _agent_notes.strip() and not _user_goal.strip():
        return msgs

    header_parts = []
    if _user_goal.strip():
        header_parts.append(f"[用户目标] {_user_goal}")
    if _agent_notes.strip():
        header_parts.append(f"[工作笔记]\n{_agent_notes}")

    header = HumanMessage(content="\n\n".join(header_parts))
    result = list(msgs)

    # 插入到系统提示之后
    system_count = sum(1 for m in result if isinstance(m, SystemMessage))
    result.insert(system_count, header)
    return result


# ── 上下文压缩 ──

def _estimate_tokens(msgs: list) -> int:
    total = 0
    for m in msgs:
        content = getattr(m, "content", "") or ""
        total += len(content) // 2
        if isinstance(m, AIMessage) and m.tool_calls:
            for tc in m.tool_calls:
                total += len(json.dumps(tc.get("args", {}))) // 2
    return total


def _count_rounds_and_errors(messages: list) -> tuple[int, int]:
    rounds = sum(1 for m in messages if isinstance(m, AIMessage) and m.tool_calls)
    errors = sum(1 for m in messages if isinstance(m, ToolMessage) and m.content.startswith("[错误]"))
    return rounds, errors


async def _compress_context(msgs: list) -> list:
    system_msgs = [m for m in msgs if isinstance(m, SystemMessage)]
    first_user = next((m for m in msgs if isinstance(m, HumanMessage) and not m.content.startswith("[")), None)

    recent = msgs[-KEEP_RECENT:]
    exclude_ids = {id(m) for m in system_msgs + recent + ([first_user] if first_user else [])}
    old = [m for m in msgs if id(m) not in exclude_ids]

    if len(old) <= 2:
        return msgs

    old_text_parts = []
    for m in old:
        content = getattr(m, "content", "") or ""
        if isinstance(m, AIMessage) and m.tool_calls:
            names = [tc["name"] for tc in m.tool_calls]
            old_text_parts.append(f"[调用] {', '.join(names)}")
        elif isinstance(m, ToolMessage):
            label = "❌" if content.startswith("[错误]") else "✓"
            old_text_parts.append(f"[结果 {label}] {content[:200]}")

    compress_prompt = (
        "将以下浏览器操作历史压缩为 ≤400 字的摘要，保留已完成步骤、关键发现和错误：\n\n"
        + "\n".join(old_text_parts)
    )

    try:
        resp = await _summarize_llm.ainvoke([HumanMessage(content=compress_prompt)])
        summary = str(resp.content).strip()
    except Exception:
        summary = f"已压缩 {len(old)} 条历史"

    result = list(system_msgs)
    if first_user:
        result.append(first_user)
    result.append(HumanMessage(content=f"[上下文摘要] {summary}"))
    result.extend(recent)
    return result


# ── LangGraph 图 ──

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


def build_browser_graph():
    """构建 Plan-then-Execute Agent 图。

    图结构:
        START → planner → agent → [路由]
                            ↑       /  |  \
                            └─tools  limit  END
                                     ↓
                                  limit_reached → END
    """
    graph = StateGraph(AgentState)
    llm_with_tools = llm.bind_tools(AGENT_TOOLS)
    tool_node = ToolNode(AGENT_TOOLS)

    # ── 规划节点 ──

    async def planner_node(state: AgentState):
        """分析用户意图，生成结构化执行计划并存入笔记。"""
        global _agent_notes, _user_goal

        user_msgs = [m for m in state["messages"] if isinstance(m, HumanMessage)]
        if not user_msgs:
            return {}
        _user_goal = user_msgs[-1].content

        if not ENABLE_PLANNING:
            return {}

        plan_prompt = f"""你是任务规划助手。分析用户任务，拆解为浏览器操作步骤。

用户任务：{_user_goal}

请严格按以下格式输出（确保 Agent 可直接按步骤执行）：

## 任务目标
（一句话概括）

## 执行步骤
- [ ] 1. （第一步操作——打开哪个页面、点击什么、填什么）
- [ ] 2. （第二步，依此类推）
...

## 完成标准
（一句话说明怎样算完成）

要求：
- 每步是一个具体浏览器操作（browser_open、browser_snapshot、browser_click、browser_fill、browser_scroll 等）
- 步骤按依赖排序
- 输入/点击目标尽可能具体
- 控制在 5-10 步"""

        try:
            response = await llm.ainvoke([HumanMessage(content=plan_prompt)])
            _agent_notes = str(response.content).strip()
            logger.info("规划完成：%s", _agent_notes[:100])
            return {"messages": [AIMessage(content="计划已生成，开始执行。")]}
        except Exception as exc:
            logger.error("规划失败: %s", exc)
            _agent_notes = f"任务: {_user_goal}\n- [ ] 执行用户任务"
            return {"messages": [AIMessage(content="规划跳过，直接执行。")]}

    # ── 执行节点 ──

    async def agent_node(state: AgentState):
        """执行推理节点。调用前注入笔记并视情况压缩上下文。"""
        msgs = list(state["messages"])

        if not any(isinstance(m, SystemMessage) for m in msgs):
            msgs.insert(0, SystemMessage(content=EXECUTOR_SYSTEM_PROMPT))

        # 注入笔记到上下文首部
        msgs = _inject_notes(msgs)

        # 上下文过长则压缩
        est = _estimate_tokens(msgs)
        if est > MAX_CONTEXT_TOKENS:
            logger.info("上下文 %d tokens → 压缩", est)
            msgs = await _compress_context(msgs)
            msgs = _inject_notes(msgs)
            logger.info("压缩后 %d tokens", _estimate_tokens(msgs))

        response = await llm_with_tools.ainvoke(msgs)
        return {"messages": [response]}

    # ── 终止节点 ──

    async def limit_reached_node(state: AgentState):
        rounds, errors = _count_rounds_and_errors(state["messages"])
        reason = f"错误次数已达 {errors} 次" if errors >= MAX_ERRORS else f"步数已达 {MAX_STEPS} 步"
        return {"messages": [AIMessage(content=f"[任务终止: {reason}]")]}

    # ── 路由 ──

    def should_continue(state: AgentState):
        msgs = state["messages"]
        last = msgs[-1]
        if isinstance(last, AIMessage) and not last.tool_calls:
            return "end"
        rounds, errors = _count_rounds_and_errors(msgs)
        if errors >= MAX_ERRORS:
            return "limit"
        if rounds >= MAX_STEPS:
            return "limit"
        return "tools"

    # ── 组装图 ──

    graph.add_node("planner", planner_node)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_node("limit_reached", limit_reached_node)

    graph.set_entry_point("planner")
    graph.add_edge("planner", "agent")
    graph.add_conditional_edges(
        "agent", should_continue,
        {"tools": "tools", "limit": "limit_reached", "end": END},
    )
    graph.add_edge("tools", "agent")
    graph.add_edge("limit_reached", END)

    return graph.compile()


# ── 系统提示 ──

BROWSER_AGENT_SYSTEM_PROMPT = """你是浏览器操作执行助手。上下文首部的 [工作笔记] 中已包含执行计划，
请严格按照计划步骤顺序执行，不要重新规划或偏离计划。

═══ 执行策略 ═══

1. 每次只执行笔记中下一个未完成的步骤（标记为 [ ] 的步骤）
2. 完成一步后立刻 write_note：将该步骤改为 [x]，可补充当前发现
3. 步骤失败：标记为 [-]，记录原因，继续尝试或跳过
4. 需要查看进度时用 read_note
5. 所有步骤完成后，输出简洁的总结

═══ 操作要点 ═══

- 交互前先 browser_snapshot 了解页面
- 点击/填表必须用快照引用（@e1、@e42）
- 一次只做一步

═══ 错误恢复 ═══

- 工具报错 [错误] 时不要重复相同操作
- 引用失效 → 重新 browser_snapshot
- 某步骤连续失败 2 次 → 标记为 [-]，进入下一步"""

EXECUTOR_SYSTEM_PROMPT = BROWSER_AGENT_SYSTEM_PROMPT


# ── 交互式对话 ──

def _trim_messages(msgs: list) -> list:
    if len(msgs) <= MAX_MESSAGES:
        return msgs
    keep = msgs[-MAX_MESSAGES:]
    return [HumanMessage(content=f"[已丢弃 {len(msgs) - MAX_MESSAGES} 条旧消息")] + keep


async def _chat_loop():
    global _agent_notes, _user_goal
    agent = build_browser_graph()
    messages: list = []

    print("输入你的指令，Agent 会调用浏览器工具执行。输入 /quit 退出。")
    if ENABLE_PLANNING:
        print("(规划节点已启用，Agent 会先分析任务再执行)")
    print()

    while True:
        try:
            user_input = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue
        if user_input.lower() in ("/quit", "/exit", ":q"):
            break

        _user_goal = user_input
        _agent_notes = ""

        messages.append(HumanMessage(content=user_input))
        result = await agent.ainvoke({"messages": list(messages)})

        added = result["messages"][len(messages):]
        for m in added:
            content = getattr(m, "content", "")
            tool_calls = getattr(m, "tool_calls", None)
            if tool_calls:
                for tc in tool_calls:
                    args_str = json.dumps(tc.get("args", {}), ensure_ascii=False)
                    print(f"   🔧 {tc['name']}({args_str})")
            elif content:
                if content.startswith("笔记已保存") or content == "(暂无笔记)":
                    continue
                prefix = "⚠️ " if content.startswith("[错误]") else ""
                if content.startswith("计划已生成") or content.startswith("规划跳过"):
                    print(f"📋 {content}")
                else:
                    print(f"Agent: {prefix}{content[:300]}")

        rounds, errors = _count_rounds_and_errors(added)
        if rounds:
            print(f"   📊 {rounds} 步 · {errors} 错误")

        messages = _trim_messages(list(result["messages"]))


# ── 入口 ──

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    print("=" * 50)
    print("浏览器 Agent 交互式对话")
    print("=" * 50)
    print("确保 Chrome 已启动：google-chrome --remote-debugging-port=9222")
    print()

    async def _main():
        try:
            await _chat_loop()
        except Exception as exc:
            logger.error("运行异常: %s", exc)
        finally:
            await browser_close.ainvoke({})

    asyncio.run(_main())
