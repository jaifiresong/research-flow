# Research Flow - 自动化研究助理设计文档

## 概述

一个基于 agent-browser 的 Python CLI 工具，能自动完成"搜索 → 阅读 → 总结 → 写综述"的技术调研流程。

**使用场景**：技术调研（搜索技术文档、博客、GitHub 项目，生成技术选型报告）

**用法**：
```bash
python main.py "对比 React vs Vue vs Svelte 2026"
python main.py "对比 React vs Vue vs Svelte 2026" --max-pages 15 --output report.html
```

## 项目结构

```
research-flow/
├── main.py              # 入口：解析参数，启动研究流程
├── agent.py             # Agent 核心：LangChain 调用 OpenAI 做推理规划
├── browser.py           # 封装 agent-browser CLI 子进程调用
├── summarizer.py        # 页面内容提取 + LLM 总结
├── report.py            # 纯 f-string 生成自包含 HTML 报告
├── config.py            # 配置（模型、搜索数量等）
├── requirements.txt     # 依赖
├── .env.example         # 环境变量示例
└── output/              # 生成的报告存放目录
```

## 技术栈

| 组件 | 选择 | 说明 |
|------|------|------|
| 语言 | Python 3.11+ | 先跑通流程 |
| 浏览器自动化 | agent-browser CLI (subprocess) | Rust 原生 CLI，通过子进程调用 |
| LLM 框架 | LangChain + langchain-openai | 替代直接调用 openai SDK |
| HTML 生成 | 纯 Python f-string | 零依赖，单文件自包含，内联 CSS |
| 配置 | python-dotenv + .env | 简单直接 |

**依赖 (requirements.txt)**:
```
langchain>=0.3
langchain-openai>=0.2
python-dotenv>=1.0
```

**环境变量**:
- `OPENAI_API_KEY`：OpenAI API 密钥（必填）
- `AGENT_BROWSER_PATH`：agent-browser 路径（可选，默认 `agent-browser`）

## 核心流程

```
用户输入主题
    ↓
阶段1：规划 (agent.py)
  LLM 生成搜索关键词 + 目标网站列表
    ↓
阶段2：搜索 (browser.py + summarizer.py)
  agent-browser 打开 Google，搜索，收集结果链接
    ↓
阶段3：阅读 (browser.py + summarizer.py)
  逐个打开链接，抓取页面文本，LLM 提取关键信息
    ↓
阶段4：总结 (report.py)
  汇总所有页面信息，LLM 生成结构化综述
    ↓
输出 HTML 报告
```

## 各阶段详细设计

### 阶段1：规划 (agent.py)

调用 LangChain + OpenAI，输入用户主题，输出结构化 JSON：

```json
{
  "keywords": ["React vs Vue 2026", "frontend framework comparison 2026"],
  "sites": ["github.com", "npmtrends.com", "stackoverflow.com"],
  "max_pages": 20
}
```

LLM 根据主题自动判断该搜索哪些关键词、访问哪些技术网站。

### 阶段2：搜索 (browser.py + summarizer.py)

1. `agent-browser open https://www.google.com`
2. `agent-browser fill` 搜索框填入关键词
3. `agent-browser press Enter` 触发搜索
4. `agent-browser snapshot` 获取搜索结果的可访问性树
5. 从 snapshot 中提取结果标题和 URL
6. 对规划中指定的网站（如 github.com），直接构造搜索 URL 访问

### 阶段3：阅读 (browser.py + summarizer.py)

对每个收集到的 URL：

1. `agent-browser open <url>` 打开页面
2. 等待页面加载完成
3. `agent-browser get text body` 获取页面文本内容
4. 截取前 3000 字符（避免 token 超限）
5. 调用 LangChain + OpenAI 提取：
   - 页面标题
   - 核心观点（3-5 条）
   - 关键数据/指标
   - 优缺点（如适用）

每个页面提取结果为结构化 dict。

### 阶段4：总结 (report.py)

将所有页面的提取结果汇总为 context，调用 LLM 生成综述：

- **摘要**：200 字概述研究主题
- **各技术/方案对比**：详细分析
- **优缺点表格**：结构化对比
- **结论与建议**：基于数据的推荐

## HTML 报告设计

纯 f-string 生成，零外部依赖，单文件可直接打开：

- 内联 CSS 样式（简洁排版）
- 不依赖任何外部 CDN 或资源
- 包含：标题、生成时间、摘要、正文各章节、来源链接列表
- 丑一点没关系，重点是内容完整可读

## 错误处理

| 场景 | 处理方式 |
|------|----------|
| agent-browser 命令失败 | 记录日志，跳过该页面，继续下一个 |
| OpenAI API 超时/错误 | 重试 2 次，仍失败则终止并输出已收集的部分结果 |
| 页面内容为空或无法访问 | 跳过，不计入已读页面数 |
| 所有页面都失败 | 报错退出，提示用户检查网络和 agent-browser 安装 |
| 用户未设置 OPENAI_API_KEY | 启动时检查，缺失则报错提示 |

## 配置项

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `--max-pages` | 20 | 最多阅读页面数 |
| `--output` | `output/report_<timestamp>.html` | 输出文件路径 |
| `OPENAI_API_KEY` | (必填) | OpenAI API 密钥 |
| `AGENT_BROWSER_PATH` | `agent-browser` | agent-browser CLI 路径 |
| `OPENAI_MODEL` | `gpt-4o` | 使用的模型 |
