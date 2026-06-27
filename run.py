"""Pico 交互入口。"""
from agents.supervisor import build_graph
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
import sqlite3

load_dotenv()

conn = sqlite3.connect("tmp/pico_checkpoints.db", check_same_thread=False)
checkpointer = SqliteSaver(conn)


def confirm(result, graph, config):
    state = graph.get_state(config)
    while state.interrupts:
        for interrupt_data in state.interrupts:
            print(f"\n⚠️  中断类型: {interrupt_data.value}")
            if isinstance(interrupt_data.value, dict) and interrupt_data.value.get("type") == "confirm_dangerous":
                print(f"\n⚠️  {interrupt_data.value['message']}")
                answer = input("批准？(y/n): ").strip().lower()
                approved = answer in ("y", "yes", "是")

                # 用 Command(resume=...) 恢复执行
                result = graph.invoke(
                    Command(resume=approved),
                    config=config
                )
                state = graph.get_state(config)
            else:
                print(f"未知中断类型，跳过")
                state = None
                break
        if state is None or not state.interrupts:
            break

    return result


def main():
    graph = build_graph(checkpointer=checkpointer)
    # 会话配置：thread_id 区分不同会话
    config = {"configurable": {"thread_id": "default"}}
    print("Pico 已启动。输入消息，或 /exit 退出。\n")

    messages = []
    while True:
        user_input = input("你: ").strip()
        if user_input.lower() == "/exit":
            break
        if not user_input:
            continue

        result = graph.invoke(
            {"messages": messages + [HumanMessage(content=user_input)]},
            config=config,
        )
        result = confirm(result, graph, config)

        messages = result["messages"]
        last_msg = messages[-1]
        print(f"Pico: {last_msg.content}\n")


if __name__ == "__main__":
    main()
