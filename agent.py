"""浏览器 Agent —— 用 LangGraph 自建控制循环，白盒可控每一步。"""
import asyncio
import json
import logging
from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
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

BROWSER_AGENT_SYSTEM_PROMPT = """你是一个浏览器自动化助手，可以通过工具完全控制一个浏览器。

操作要点：
- 交互前务必先用 browser_snapshot 了解页面上有哪些可交互元素
- 点击或填表时，必须使用快照中返回的元素引用（如 @e1、@e42）
- 每次只执行一步，观察结果后再决定下一步

错误恢复：
- 工具返回 [错误] 开头的信息时，不要重复同样的操作
- 如果元素引用报错（如 "No node with given id"），页面可能已变化，重新 browser_snapshot 获取最新引用
- 重复失败 3 次以上应该停止并报告原因

输出原则：
- 最终回复要简洁，直接说完成了什么或遇到了什么问题
- 工具返回的原始数据不需要逐字复述
- 不需要继续调用工具时，直接输出最终结果即可"""

# 单轮最多执行 N 步（每步 = LLM 调用一次工具）
MAX_STEPS = 12
# 最多连续错误次数
MAX_ERRORS = 3
# 多轮对话中保留的最大消息数
MAX_MESSAGES = 40


# ── LangGraph 状态与图 ──

class AgentState(TypedDict):
    """Agent 状态：messages 用 add_messages reducer 自动追加快照。"""
    messages: Annotated[list, add_messages]


def _count_rounds_and_errors(messages: list) -> tuple[int, int]:
    """统计已执行的工具轮数和错误次数。"""
    rounds = sum(1 for m in messages if isinstance(m, AIMessage) and m.tool_calls)
    errors = sum(1 for m in messages if isinstance(m, ToolMessage) and m.content.startswith("[错误]"))
    return rounds, errors


def build_browser_graph():
    """构建浏览器 Agent 的控制图。

    图结构:
        START → agent → [should_continue?]
                         /         |        \
                     tools      limit       END
                       ↓          ↓
                     agent    limit_reached
                                  ↓
                                END

    - agent   : LLM 推理，决定下一步（调用工具 or 输出结果）
    - tools   : 执行工具调用，结果回传给 agent
    - limit   : 步数/错误超限时进入，生成终止说明
    - should_continue : 根据消息状态决定下一步路由
    """
    graph = StateGraph(AgentState)

    llm_with_tools = llm.bind_tools(BROWSER_TOOLS)
    tool_node = ToolNode(BROWSER_TOOLS)

    async def agent_node(state: AgentState):
        """LLM 推理节点。"""
        msgs = list(state["messages"])
        if not any(isinstance(m, SystemMessage) for m in msgs):
            msgs.insert(0, SystemMessage(content=BROWSER_AGENT_SYSTEM_PROMPT))
        response = await llm_with_tools.ainvoke(msgs)
        return {"messages": [response]}

    async def limit_reached_node(state: AgentState):
        """达到步数/错误上限时，生成终止消息。"""
        rounds, errors = _count_rounds_and_errors(state["messages"])
        if errors >= MAX_ERRORS:
            reason = f"错误次数已达 {errors} 次"
        else:
            reason = f"步数已达 {MAX_STEPS} 步"
        return {"messages": [AIMessage(content=f"[任务终止: {reason}]")]}

    def should_continue(state: AgentState):
        """根据状态决定下一步路由。"""
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

    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_node("limit_reached", limit_reached_node)

    graph.set_entry_point("agent")
    graph.add_conditional_edges(
        "agent", should_continue,
        {"tools": "tools", "limit": "limit_reached", "end": END},
    )
    graph.add_edge("tools", "agent")
    graph.add_edge("limit_reached", END)

    return graph.compile()


# ── 交互式对话 ──


def _trim_messages(msgs: list) -> list:
    """修剪消息列表，防止上下文溢出。"""
    if len(msgs) <= MAX_MESSAGES:
        return msgs
    keep = msgs[-MAX_MESSAGES:]
    return [HumanMessage(content=f"[已丢弃 {len(msgs) - MAX_MESSAGES} 条旧消息以节省上下文]")] + keep


async def _chat_loop():
    """交互式多轮对话。"""
    agent = build_browser_graph()
    messages: list = []

    print("输入你的指令，Agent 会调用浏览器工具执行。输入 /quit 退出。")
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

        messages.append(HumanMessage(content=user_input))
        result = await agent.ainvoke({"messages": list(messages)})

        # 提取新增消息并展示
        added = result["messages"][len(messages):]
        for m in added:
            content = getattr(m, "content", "")
            tool_calls = getattr(m, "tool_calls", None)
            if tool_calls:
                for tc in tool_calls:
                    args_str = json.dumps(tc.get("args", {}), ensure_ascii=False)
                    print(f"   🔧 {tc['name']}({args_str})")
            elif content:
                prefix = "⚠️ " if content.startswith("[错误]") else ""
                print(f"Agent: {prefix}{content[:300]}")

        # 输出本轮统计
        rounds, errors = _count_rounds_and_errors(added)
        if errors:
            print(f"   📊 本轮: {rounds} 步 · {errors} 错误")

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
