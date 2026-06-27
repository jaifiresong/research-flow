"""消息裁剪：当历史过长时，用 LLM 摘要旧消息。混合策略：摘要旧消息 + 保留最近 K 条。"""
import json
from typing import cast

from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel

from tools.base import workplace_dir

# 超过此数量时触发裁剪
MAX_MESSAGES = 20
# 保留最近多少条不动（≥ 一次工具调用往返，给安全切点留容错空间）
KEEP_RECENT = 12

SYSTEM_PROMPT = f"""\
你是 Pico，一个文件操作助手。你拥有读写文件、编辑文件和执行 bash 的能力。

工作区路径：{workplace_dir}
所有文件操作的 path 参数均为相对于工作区的路径，不可逾越工作区边界。

## 你能用的工具
- read_file(path, offset, limit) —— 读取文件内容
- write_file(path, content) —— 创建或覆盖文件
- edit_file(path, old_text, new_text) —— 精确替换文件中的文本
- run_bash(command, timeout) —— 执行 shell 命令
 
## 行为准则
- 编辑文件前，先用 read_file 确认文件现状。
- edit_file 的 old_text 必须精确匹配原文，在文件中唯一。
- 每次只做一件事，做完再看下一步。不要一口气预测太多步。
- 如果文件操作失败，读错误信息，分析原因，再尝试修正。
- 不要执行危险命令（rm -rf、格式化磁盘等），遇到可疑命令先警告用户。
- 回复简洁，直接给出结果，不要长篇大论。

## 格式
- 代码放在 Markdown 代码块中，标注语言。
- 文件路径用反引号包裹。
- 用中文回复用户。
"""

SUMMARY_SYSTEM = """你是一个对话摘要器。用中文摘要以下对话历史，控制在 200 字以内。
重点保留：
- 用户执行了哪些文件操作（路径 / 内容 / 结果）
- 用户的核心意图和目标
- 重要的结论或约定"""


def get_system_prompt_with_skill() -> str:
    """返回完整系统提示词 = 基础提示词 + 技能菜单。"""
    return SYSTEM_PROMPT


class TrimResult(BaseModel):
    messages: list[BaseMessage]
    system_msg: list[BaseMessage]
    trimmed: bool
    summary: str

    def full_messages(self):
        return [*self.system_msg, *self.messages]


class Trimmer:
    """消息裁剪器。混合策略：摘要旧消息 + 保留最近 K 条。"""

    def __init__(self, messages: list[BaseMessage], summary: str, llm: BaseChatModel):
        self.messages = messages
        self.summary = summary
        self.llm = llm

        print("-" * 50, "消息裁剪器：原始消息", "-" * 50)
        for msg in self.messages:
            print(msg.type, msg.model_dump_json())
        print("-" * 50, f"消息裁剪器：当前 {len(self.messages)} 条", "-" * 50)

    def _should_trim(self) -> bool:
        """判断是否需要裁剪。"""
        return len(self.messages) > MAX_MESSAGES

    def _safe_split_idx(self) -> int:
        """安全切点：防止 ToolMessage 与它的 AIMessage(tool_calls) 被切断。
        如果保留区有 ToolMessage 引用了旧区 AIMessage 的 tool_call_id，
        则该 AIMessage 移入保留区。"""
        rough = len(self.messages) - KEEP_RECENT
        recent = self.messages[rough:]

        # 收集保留区 ToolMessage 引用的 tool_call_id
        pending_ids: set[str] = set()
        for m in recent:
            if isinstance(m, ToolMessage):
                tc_id = getattr(m, "tool_call_id", None)
                if tc_id:
                    pending_ids.add(tc_id)

        if not pending_ids:
            return rough

        # 旧区从右往左找匹配的 AIMessage，切点移到它之前
        for i in range(rough - 1, -1, -1):
            m = self.messages[i]
            if isinstance(m, AIMessage):
                tcs = getattr(m, "tool_calls", None) or []
                if any(tc.get("id") in pending_ids for tc in tcs if tc.get("id")):
                    return i  # AIMessage 归入保留区
        return rough

    def _generate_summary(self, old_messages: list[BaseMessage]) -> str:
        """用 LLM 对旧消息生成摘要。"""
        text_parts = []
        for m in old_messages:
            content = getattr(m, "content", "") or ""
            if content:
                text_parts.append(f"[{m.type}] {content}")
        old_text = "\n".join(text_parts)

        response = self.llm.invoke([
            SystemMessage(content=SUMMARY_SYSTEM),
            SystemMessage(content=f"之前的对话历史摘要：<summary>{self.summary}</summary>"),
            HumanMessage(content=f"对话历史：<old_text>{old_text}</old_text>")
        ])
        return cast(str, response.content)

    def trimmed_messages(self) -> TrimResult:
        """返回裁剪后的消息列表（含系统提示词前置）。"""

        if not self._should_trim():
            return TrimResult(
                messages=self.messages,
                system_msg=[SystemMessage(content=get_system_prompt_with_skill())],
                trimmed=False,
                summary="",
            )

        split_idx = self._safe_split_idx()
        old = self.messages[:split_idx]
        recent = self.messages[split_idx:]

        print(f"裁剪触发：摘要前 {len(old)} 条，保留最近 {len(recent)} 条")
        summary = self._generate_summary(old)

        sys_msg = [
            SystemMessage(content=get_system_prompt_with_skill()),
            SystemMessage(content=f"[对话历史摘要]\n{summary}"),
        ]

        print(f"裁剪完成: ", summary)

        return TrimResult(
            messages=recent,
            system_msg=sys_msg,
            trimmed=True,
            summary=summary,
        )
