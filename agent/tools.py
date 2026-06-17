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
