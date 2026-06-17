from typing import Annotated, TypedDict

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.types import interrupt

from config import OPENAI_API_KEY
from cdp.tools import BROWSER_TOOLS
from agent.tools import update_memory, read_memory, get_memory, reset_memory
from agent.compressor import compress_tool_result
from agent.prompts import PLANNER_SYSTEM_PROMPT, EXECUTOR_SYSTEM_PROMPT

MAX_STEPS = 30
MAX_ERRORS = 5

llm = ChatOpenAI(
    model="deepseek-chat",
    api_key=OPENAI_API_KEY,
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

    if isinstance(user_response, str) and user_response.lower().strip() in ("confirmed", "y", "yes", "确认", "确认执行"):
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
                ToolMessage(content=summary, tool_call_id=m.tool_call_id, name=m.name, id=m.id)
            )

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
