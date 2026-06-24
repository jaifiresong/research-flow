# Research Flow

AI-driven browser automation framework with anti-detection CDP driver, MCP integration, and LangGraph agent orchestration.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Research Flow                        │
│                                                         │
│  ┌─────────────┐    ┌──────────────┐    ┌────────────┐ │
│  │  AI Agent   │───▶│  Structured  │───▶│ LangGraph   │ │
│  │  (LLM)      │    │  Memory      │    │ Orchestrator│ │
│  └─────────────┘    └──────────────┘    └──────┬─────┘ │
│                                                │        │
│                                   Plan → Execute → Tools│
│                                                │        │
│  ┌─────────────────────────────────────────────▼──────┐ │
│  │              CDP Driver Layer                       │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │ │
│  │  │ Snapshot │  │  Click   │  │   Fill/Scroll    │  │ │
│  │  │ (AXTree) │  │ (DOM)    │  │   (DOM events)   │  │ │
│  │  └──────────┘  └──────────┘  └──────────────────┘  │ │
│  │                                                     │ │
│  │  WebSocket ←──→ Chrome DevTools Protocol (CDP)      │ │
│  └──────────────────────────┬──────────────────────────┘ │
│                             │                             │
│  ┌──────────────────────────▼──────────────────────────┐ │
│  │                 MCP Server                           │ │
│  │  (Stdio JSON-RPC — Claude Desktop / Codex / etc.)    │ │
│  └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

## Key Features

- **Anti-detection CDP driver** — native WebSocket CDP client that avoids triggering bot detection by skipping `.enable()` event subscriptions (see [Background](#background))
- **Plan-then-Execute Agent** — LangGraph-based graph that first generates a structured execution plan, then executes step-by-step with progress tracking
- **Structured memory** — plan, findings, and context are persisted in a structured format injected at the top of the LLM context for reliable goal tracking
- **MCP Server** — exposes browser automation tools via the Model Context Protocol, compatible with Claude Desktop, Codex, and other MCP clients
- **Context compression** — automatic summarization of tool results when context exceeds token limits
- **Interactive CLI** — chat-based REPL for direct agent interaction with real-time tool call visualization

## Quick Start

### Prerequisites

- Python ≥ 3.12
- Chrome/Chromium with remote debugging enabled

### Installation

```bash
git clone https://github.com/yourusername/research-flow.git
cd research-flow
uv sync
```

### Configure

```bash
cp .env.example .env
# Edit .env and set your OPENAI_API_KEY and OPENAI_MODEL
```

### Launch Chrome

```bash
google-chrome --remote-debugging-port=9222
```

### Run the Agent (Interactive)

```bash
uv run python main.py
```

Example session:
```
你: 打开 BOSS直聘，搜索"Python 开发"岗位，提取前 5 个结果的岗位名称、薪资和公司

📋 计划已生成：
## 任务目标
搜索 BOSS直聘 Python 开发岗位并提取前5条结果
## 执行步骤
- [ ] 1. 打开 http://www.zhipin.com/web/geek/jobs
  ...
确认执行？(y/n/修改): y

Agent: 正在执行...
  🔧 browser_snapshot()
  🔧 browser_fill({"ref": "@e12", "text": "Python 开发"})
  ...
```

### Run as MCP Server

```bash
uv run python cdp/mcp_server.py --host 127.0.0.1 --port 9222
```

Configure in Claude Desktop `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "cdp_driver": {
      "command": "uv",
      "args": ["run", "python", "/path/to/research-flow/cdp/mcp_server.py", "--host", "127.0.0.1", "--port", "9222"]
    }
  }
}
```

## Project Structure

```
research-flow/
├── main.py                  # Interactive agent CLI entrypoint
├── agent.py                 # Agent build & chat loop (standalone variant)
├── config.py                # Configuration (LLM API key, model)
├── agent/                   # AI Agent layer
│   ├── graph.py             # LangGraph graph definition (Plan-then-Execute)
│   ├── memory.py            # Structured memory (plan/findings/context)
│   ├── prompts.py           # System prompts for planner & executor
│   ├── tools.py             # Agent memory tools (update_memory, read_memory)
│   └── compressor.py        # Context compression & message trimming
├── cdp/                     # CDP browser driver layer
│   ├── tools.py             # Browser automation tools (snapshot/click/fill/...)
│   └── mcp_server.py        # MCP stdio JSON-RPC server
└── tests/
    └── test_memory.py       # Memory unit tests
```

## Background

Most browser automation tools (Puppeteer, Playwright, Selenium) subscribe to CDP events via `.enable()` calls — e.g., `Page.enable()`, `Runtime.enable()`. These subscriptions create detectable CDP sessions that anti-bot services can observe. On sites like BOSS直聘 (zhipin.com), this triggers an immediate redirect to `about:blank`.

This project's CDP driver takes a different approach:

- **Never calls `.enable()`** on Page, Runtime, Network domains
- Uses **direct command calls** (`Page.navigate`, `Runtime.evaluate`, `Accessibility.getFullAXTree`) without event subscriptions
- Connects via **raw WebSocket** with only `websockets` as dependency
- Uses **accessibility tree** for page interaction instead of DOM selectors, generating `@eN` ref-based element handles

### Why this matters

| Approach | Page.enable() | Runtime.enable() | Bot Detection Risk |
|----------|:---:|:---:|:---:|
| Puppeteer / Playwright | ✓ | ✓ | High |
| agent-browser (CDP mode) | ✓ | ✓ | High |
| **Research Flow CDP Driver** | ✗ | ✗ | Low |

## License

MIT
