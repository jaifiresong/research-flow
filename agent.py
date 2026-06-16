import asyncio
import json
import logging
from typing import Optional

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from cdp.tools import BROWSER_TOOLS, browser_close
from config import OPENAI_API_KEY, OPENAI_MODEL

logger = logging.getLogger(__name__)

llm = ChatOpenAI(
    model=OPENAI_MODEL,
    api_key=OPENAI_API_KEY,
    base_url="https://api.deepseek.com"
)

# 浏览器 Agent 的系统提示词
BROWSER_AGENT_SYSTEM_PROMPT = """你是一个浏览器自动化助手，可以通过工具完全控制一个浏览器。
你能：借助工具控制网页 

操作要点：
- 交互前务必先用 browser_snapshot 了解页面上有哪些可交互元素
- 点击或填表时，必须使用快照中返回的元素引用（如 @e1、@e42）
- 每次只执行一步，观察结果后再决定下一步"""


def create_browser_agent():
    """创建带浏览器控制工具的 LangChain Agent。

    返回 CompiledStateGraph，用 .ainvoke({"messages": [...]}) 调用。
    """
    return create_agent(
        model=llm,
        tools=BROWSER_TOOLS,
        system_prompt=BROWSER_AGENT_SYSTEM_PROMPT,
    )


# ── 交互式对话 ──


async def _chat_loop():
    """交互式多轮对话：持续接收用户输入，与 LLM Agent 对话。"""
    agent = create_browser_agent()
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

        # 提取新增消息
        added = result["messages"][len(messages):]
        for m in added:
            content = getattr(m, "content", "")
            tool_calls = getattr(m, "tool_calls", None)
            if tool_calls:
                for tc in tool_calls:
                    args_str = json.dumps(tc.get("args", {}), ensure_ascii=False)
                    print(f"   🔧 {tc['name']}({args_str})")
            elif content:
                print(f"Agent: {content}")

        messages = list(result["messages"])


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
    try:
        asyncio.run(_chat_loop())
    finally:
        asyncio.run(browser_close.ainvoke({}))

