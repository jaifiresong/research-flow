"""Pico — 最小化 agent。本课跑通工具调用骨架。"""
from typing import Annotated, TypedDict
import operator
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage, SystemMessage
from langchain_deepseek import ChatDeepSeek
from langgraph.graph import StateGraph, END
from langgraph.types import Overwrite

from tools.base import read_file, write_file, edit_file, run_bash, workplace_dir
from trimmer import Trimmer

TOOLS = [read_file, write_file, edit_file, run_bash]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}


# ── 状态：消息列表自动追加 ──────────────────
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], operator.add]
    summary: str


# ── LLM 节点：调用模型，返回消息 ────────────
def agent_node(state: AgentState) -> dict:
    llm = ChatDeepSeek(
        model="deepseek-v4-flash",
        temperature=0,
    )

    summary = state.get('summary', '')

    llm_with_tools = llm.bind_tools(TOOLS)
    tr = Trimmer(state["messages"], summary, llm).trimmed_messages()
    response = llm_with_tools.invoke(tr.full_messages())

    if tr.trimmed:
        return {"messages": Overwrite(tr.messages + [response]), "summary": tr.summary}

    return {"messages": [response], "summary": summary}


def tools_node(state: AgentState) -> dict:
    """执行 LLM 请求的工具调用。"""
    last_msg = state["messages"][-1]
    print("LLM 工具调用：", last_msg.model_dump_json())
    results = []
    for tc in last_msg.tool_calls:
        tool = TOOLS_BY_NAME.get(tc["name"])
        if tool:
            output = tool.invoke(tc["args"])
        else:
            output = f"未知工具：{tc['name']}"
        results.append(ToolMessage(
            content=output, tool_call_id=tc["id"]
        ))
    return {"messages": results}


# ── 路由：没有 tool_calls → end ────────────
def should_continue(state: AgentState) -> str:
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return "end"


# ── 构建图 ─────────────────────────────────
def build_graph(checkpointer=None):
    graph = StateGraph(AgentState)

    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)

    graph.add_edge("tools", "agent")
    graph.add_conditional_edges("agent", should_continue, {
        "tools": "tools",
        "end": END
    })

    graph.set_entry_point("agent")  # 入口
    return graph.compile(checkpointer=checkpointer)
