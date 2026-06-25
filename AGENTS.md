# Research Flow — AGENTS.md

## Python 与环境

- Python ≥ 3.12，使用 uv 管理依赖（`uv sync` → 安装全部依赖）
- Python 路径：`D:\jaifiresong\bili2text\.venv\Scripts\python.exe`
- 需要 `.env` 文件包含 `OPENAI_API_KEY` 和 `OPENAI_MODEL`（复制 `.env.example`）
- LLM 硬编码为 `https://api.deepseek.com`，模型 `deepseek-chat`，见 `agent/graph.py:20` 和 `agent/compressor.py:9`
- 临时文件使用项目内的 `tmp/` 目录（已加入 gitignore），**禁止使用系统的 `$env:TEMP` 或 `$env:TMP`**

## 命令

| 动作 | 命令 |
|--------|---------|
| 运行交互式 agent | `uv run python main.py` |
| 运行独立对话 | `uv run python agent.py` |
| 运行 MCP 服务 | `uv run python cdp/mcp_server.py` |
| 运行测试 | `uv run pytest` |
| 单个测试 | `uv run pytest tests/test_memory.py::test_name -v` |

## 架构

- **两个入口**：`main.py`（交互式 CLI，有确认步骤）和 `agent.py`（独立对话）
- **两种图结构**：`agent/graph.py`（主图 — LangGraph + MemorySaver 检查点）和 `agent.py`（独立版 — 无检查点）
- **先规划后执行**：规划节点 → 确认（interrupt）→ agent 循环调用工具 → 超限/结束
- **结构化记忆**：`agent/memory.py` — `StructuredMemory`，含 plan/findings/context 三个区块，注入到上下文顶部
- **反检测 CDP**：跳过 `.enable()` 调用以避免触发反爬
- **MCP 服务**：stdio JSON-RPC 协议，通过 MCP 暴露浏览器工具

## 已知损坏状态

- `cdp/tools.py` **缺失**（`agent.py:14` 和 `agent/graph.py:12` 引用了它）— agent 启动即崩溃
- `cdp/__init__.py` 为空 — 没有 `CDPClient` 类，尽管 `boss_fktest_*.py` 导入了它

## 测试

- 只有 `tests/test_memory.py`（pytest，无需 asyncio 标记）
- 没有 CDP 集成测试

## 代码风格

- LangChain 工具使用 `@tool` 装饰器装饰异步函数
- LangGraph 状态用 `TypedDict` 定义，`Annotated[list, add_messages]` 作为消息字段
- 记忆是全局单例（`_memory = StructuredMemory()`）
- CDP 工具目前采用同步 LangChain 工具模式
