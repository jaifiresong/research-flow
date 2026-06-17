import asyncio
import json
import logging

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langgraph.types import Command
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
