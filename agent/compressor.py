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
