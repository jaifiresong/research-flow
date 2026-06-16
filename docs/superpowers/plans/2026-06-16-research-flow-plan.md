# Research Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python CLI that automates "search → read → summarize → write review" for technical research using agent-browser and LangChain.

**Architecture:** A single-entry-point Python script orchestrates 4 phases: planning (LLM generates search strategy), searching (agent-browser collects URLs), reading (agent-browser extracts page content + LLM summarizes each), and reporting (LLM generates HTML review). Each phase is a separate module with clear interfaces.

**Tech Stack:** Python 3.11+, LangChain + langchain-openai, agent-browser CLI (subprocess), pure f-string HTML generation

---

## File Structure

```
research-flow/
├── main.py              # Entry point: argparse, orchestration of 4 phases
├── config.py            # Config loading from env vars and CLI args
├── browser.py           # Wrapper around agent-browser CLI subprocess calls
├── agent.py             # LangChain chains: planning, page summarization, review generation
├── report.py            # Pure f-string HTML report generation (no dependencies)
├── requirements.txt     # langchain, langchain-openai, python-dotenv
├── .env.example         # Template for environment variables
└── output/              # Default output directory for generated reports
```

---

### Task 1: Project Setup

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `config.py`
- Create: `output/.gitkeep`

- [ ] **Step 1: Create requirements.txt**

```
langchain>=0.3
langchain-openai>=0.2
python-dotenv>=1.0
```

- [ ] **Step 2: Create .env.example**

```
OPENAI_API_KEY=sk-your-key-here
# Optional: override agent-browser path
# AGENT_BROWSER_PATH=agent-browser
# Optional: override model
# OPENAI_MODEL=gpt-4o
```

- [ ] **Step 3: Create config.py**

```python
import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY environment variable is required")

AGENT_BROWSER_PATH = os.getenv("AGENT_BROWSER_PATH", "agent-browser")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
DEFAULT_MAX_PAGES = 20
DEFAULT_OUTPUT_DIR = "output"
```

- [ ] **Step 4: Create output directory**

```bash
mkdir -p output
touch output/.gitkeep
```

- [ ] **Step 5: Commit**

```bash
git add requirements.txt .env.example config.py output/.gitkeep
git commit -m "feat: project setup with config and dependencies"
```

---

### Task 2: Browser Wrapper (browser.py)

**Files:**
- Create: `browser.py`

- [ ] **Step 1: Create browser.py with agent-browser subprocess wrapper**

```python
import subprocess
import json
import logging
from typing import Optional

from config import AGENT_BROWSER_PATH

logger = logging.getLogger(__name__)


def run_browser_command(args: list[str], timeout: int = 30) -> Optional[str]:
    """Run an agent-browser command and return stdout, or None on failure."""
    cmd = [AGENT_BROWSER_PATH] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            logger.warning(f"Command failed: {' '.join(cmd)}\nstderr: {result.stderr}")
            return None
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.warning(f"Command timed out: {' '.join(cmd)}")
        return None
    except FileNotFoundError:
        logger.error(f"agent-browser not found at '{AGENT_BROWSER_PATH}'. Is it installed?")
        return None


def open_url(url: str) -> bool:
    """Open a URL in agent-browser. Returns True on success."""
    result = run_browser_command(["open", url], timeout=30)
    return result is not None


def get_page_text() -> Optional[str]:
    """Get the text content of the current page body."""
    return run_browser_command(["get", "text", "body"], timeout=15)


def get_snapshot() -> Optional[str]:
    """Get the accessibility tree snapshot of the current page."""
    return run_browser_command(["snapshot", "-i"], timeout=15)


def search_google(query: str) -> Optional[str]:
    """Open Google, search for query, and return the snapshot of results."""
    if not open_url("https://www.google.com"):
        return None

    # Find the search box and fill it
    fill_result = run_browser_command(["fill", "textarea[name='q']", query], timeout=10)
    if fill_result is None:
        # Try alternative selector
        fill_result = run_browser_command(["fill", "input[name='q']", query], timeout=10)
    if fill_result is None:
        logger.warning("Could not find Google search box")
        return None

    # Press Enter to search
    run_browser_command(["press", "Enter"], timeout=10)

    # Wait for results to load
    run_browser_command(["wait", "3000"], timeout=10)

    return get_snapshot()


def extract_urls_from_snapshot(snapshot: str, max_urls: int = 10) -> list[str]:
    """Extract URLs from an agent-browser snapshot output.

    Looks for lines containing http/https URLs in the accessibility tree.
    """
    import re
    urls = []
    # Match URLs in the snapshot text
    url_pattern = re.compile(r'https?://[^\s\)\]\"]+')
    for match in url_pattern.finditer(snapshot):
        url = match.group(0).rstrip('/')
        # Skip Google's own URLs
        if "google.com" in url or "googleapis.com" in url:
            continue
        if url not in urls:
            urls.append(url)
        if len(urls) >= max_urls:
            break
    return urls


def close_browser():
    """Close the browser session."""
    run_browser_command(["close"], timeout=10)
```

- [ ] **Step 2: Verify syntax**

```bash
python -c "import browser; print('browser.py OK')"
```

- [ ] **Step 3: Commit**

```bash
git add browser.py
git commit -m "feat: add browser.py agent-browser wrapper"
```

---

### Task 3: LLM Agent (agent.py)

**Files:**
- Create: `agent.py`

- [ ] **Step 1: Create agent.py with LangChain chains**

```python
import json
import logging
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from config import OPENAI_API_KEY, OPENAI_MODEL

logger = logging.getLogger(__name__)

llm = ChatOpenAI(api_key=OPENAI_API_KEY, model=OPENAI_MODEL, temperature=0.7)


def plan_search(topic: str) -> dict:
    """Use LLM to generate a search plan for the given topic.

    Returns dict with keys: keywords, sites, description
    """
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a research planning assistant. Given a research topic,
generate a search plan in JSON format.

Return ONLY valid JSON with these keys:
- "keywords": list of 2-4 search queries (strings)
- "sites": list of 2-5 specific websites to check (e.g. "github.com", "stackoverflow.com")
- "description": one sentence describing the research goal

Example:
{{"keywords": ["React vs Vue 2026", "frontend framework comparison"], "sites": ["github.com", "npmtrends.com"], "description": "Compare major frontend frameworks in 2026"}}"""),
        ("human", "Research topic: {topic}")
    ])

    chain = prompt | llm | StrOutputParser()
    result = chain.invoke({"topic": topic})

    # Parse JSON from response
    try:
        # Try to extract JSON from markdown code blocks
        if "```" in result:
            json_str = result.split("```")[1]
            if json_str.startswith("json"):
                json_str = json_str[4:]
            result = json_str.strip()
        return json.loads(result)
    except (json.JSONDecodeError, IndexError):
        logger.warning(f"Failed to parse LLM response as JSON: {result}")
        return {
            "keywords": [topic],
            "sites": ["github.com", "stackoverflow.com"],
            "description": topic,
        }


def summarize_page(url: str, content: str) -> Optional[dict]:
    """Summarize a page's content using LLM.

    Returns dict with keys: title, key_points, data, pros, cons
    """
    if not content or len(content.strip()) < 50:
        return None

    # Truncate to avoid token limits
    truncated = content[:3000]

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a technical research analyst. Analyze the given web page content
and extract key information.

Return ONLY valid JSON with these keys:
- "title": the page title or main heading
- "key_points": list of 3-5 key points (strings)
- "data": list of important numbers, metrics, or facts (strings), empty list if none
- "pros": list of advantages mentioned (strings), empty list if none
- "cons": list of disadvantages mentioned (strings), empty list if none

If the content is not relevant or too short, return null."""),
        ("human", "URL: {url}\n\nContent:\n{content}")
    ])

    chain = prompt | llm | StrOutputParser()
    result = chain.invoke({"url": url, "content": truncated})

    try:
        if "```" in result:
            json_str = result.split("```")[1]
            if json_str.startswith("json"):
                json_str = json_str[4:]
            result = json_str.strip()
        if result.strip().lower() == "null":
            return None
        return json.loads(result)
    except (json.JSONDecodeError, IndexError):
        logger.warning(f"Failed to parse page summary for {url}")
        return None


def generate_review(topic: str, summaries: list[dict]) -> str:
    """Generate a comprehensive review from all page summaries.

    Returns the review as HTML content (body only, no <html> wrapper).
    """
    # Build context from summaries
    context_parts = []
    for i, s in enumerate(summaries, 1):
        if s is None:
            continue
        part = f"--- Source {i}: {s.get('title', 'Unknown')} ---\n"
        part += f"Key points: {'; '.join(s.get('key_points', []))}\n"
        if s.get('data'):
            part += f"Data: {'; '.join(s['data'])}\n"
        if s.get('pros'):
            part += f"Pros: {'; '.join(s['pros'])}\n"
        if s.get('cons'):
            part += f"Cons: {'; '.join(s['cons'])}\n"
        context_parts.append(part)

    context = "\n".join(context_parts)

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a technical research writer. Given research findings from multiple sources,
write a comprehensive review in HTML format.

Return ONLY the HTML body content (no <html>, <head>, or <body> tags).
Use these HTML elements:
- <h1> for the main title
- <h2> for section headers
- <p> for paragraphs
- <ul>/<li> for lists
- <table>/<tr>/<td> for comparisons
- <strong> for emphasis

Structure:
1. <h1> title with the research topic
2. <h2> Summary (2-3 paragraph overview)
3. <h2> Detailed Analysis (breakdown of findings)
4. <h2> Comparison (if comparing technologies, use a table)
5. <h2> Pros and Cons (structured lists)
6. <h2> Conclusion (recommendation based on evidence)

Write in a clear, professional tone. Cite specific data when available."""),
        ("human", "Research topic: {topic}\n\nFindings:\n{context}")
    ])

    chain = prompt | llm | StrOutputParser()
    return chain.invoke({"topic": topic, "context": context})
```

- [ ] **Step 2: Verify syntax**

```bash
python -c "import agent; print('agent.py OK')"
```

- [ ] **Step 3: Commit**

```bash
git add agent.py
git commit -m "feat: add agent.py with LangChain planning and summarization chains"
```

---

### Task 4: HTML Report Generator (report.py)

**Files:**
- Create: `report.py`

- [ ] **Step 1: Create report.py with pure f-string HTML generation**

```python
import os
from datetime import datetime


def generate_html_report(topic: str, review_html: str, sources: list[str], output_path: str) -> str:
    """Generate a self-contained HTML report file.

    Args:
        topic: The research topic
        review_html: HTML content from LLM review generation
        sources: List of source URLs used
        output_path: Path to write the HTML file

    Returns:
        The absolute path of the generated file
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    sources_html = ""
    for url in sources:
        sources_html += f'<li><a href="{url}" target="_blank">{url}</a></li>\n'

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{topic} - Research Report</title>
<style>
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    max-width: 900px;
    margin: 0 auto;
    padding: 20px;
    line-height: 1.6;
    color: #333;
    background: #fafafa;
}}
h1 {{ color: #1a1a1a; border-bottom: 2px solid #333; padding-bottom: 10px; }}
h2 {{ color: #2c3e50; margin-top: 30px; }}
table {{ border-collapse: collapse; width: 100%; margin: 15px 0; }}
th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
th {{ background: #f5f5f5; font-weight: 600; }}
tr:nth-child(even) {{ background: #f9f9f9; }}
ul {{ padding-left: 20px; }}
li {{ margin: 4px 0; }}
a {{ color: #3498db; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.meta {{ color: #777; font-size: 0.9em; margin-bottom: 20px; }}
.sources {{ background: #fff; padding: 15px; border: 1px solid #eee; border-radius: 4px; }}
</style>
</head>
<body>
<div class="meta">
    Generated on {timestamp} | Sources: {len(sources)}
</div>

{review_html}

<h2>References</h2>
<div class="sources">
<ol>
{sources_html}
</ol>
</div>
</body>
</html>"""

    # Ensure output directory exists
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return os.path.abspath(output_path)
```

- [ ] **Step 2: Verify syntax**

```bash
python -c "import report; print('report.py OK')"
```

- [ ] **Step 3: Commit**

```bash
git add report.py
git commit -m "feat: add report.py HTML report generator"
```

---

### Task 5: Main Entry Point (main.py)

**Files:**
- Create: `main.py`

- [ ] **Step 1: Create main.py with full orchestration flow**

```python
import argparse
import logging
import sys
from datetime import datetime

from config import DEFAULT_MAX_PAGES, DEFAULT_OUTPUT_DIR
from browser import search_google, extract_urls_from_snapshot, open_url, get_page_text, close_browser
from agent import plan_search, summarize_page, generate_review
from report import generate_html_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_research(topic: str, max_pages: int, output_path: str):
    """Run the full research flow: plan → search → read → summarize → report."""

    # Phase 1: Planning
    logger.info(f"Phase 1: Planning research for: {topic}")
    plan = plan_search(topic)
    logger.info(f"  Keywords: {plan['keywords']}")
    logger.info(f"  Sites: {plan['sites']}")

    # Phase 2: Searching
    logger.info("Phase 2: Searching for relevant pages...")
    all_urls = []

    for keyword in plan["keywords"]:
        logger.info(f"  Searching Google: {keyword}")
        snapshot = search_google(keyword)
        if snapshot:
            urls = extract_urls_from_snapshot(snapshot, max_urls=5)
            logger.info(f"  Found {len(urls)} URLs")
            for url in urls:
                if url not in all_urls:
                    all_urls.append(url)
        else:
            logger.warning(f"  Search failed for: {keyword}")

    # Limit to max_pages
    all_urls = all_urls[:max_pages]
    logger.info(f"  Total unique URLs to read: {len(all_urls)}")

    if not all_urls:
        logger.error("No URLs found. Check your network and agent-browser installation.")
        close_browser()
        sys.exit(1)

    # Phase 3: Reading and summarizing
    logger.info("Phase 3: Reading and summarizing pages...")
    summaries = []
    for i, url in enumerate(all_urls, 1):
        logger.info(f"  [{i}/{len(all_urls)}] Reading: {url}")
        if not open_url(url):
            logger.warning(f"  Failed to open: {url}")
            continue

        content = get_page_text()
        if not content:
            logger.warning(f"  No content extracted: {url}")
            continue

        summary = summarize_page(url, content)
        if summary:
            summaries.append(summary)
            logger.info(f"  Summarized: {summary.get('title', 'Unknown')}")
        else:
            logger.warning(f"  Summary failed or irrelevant: {url}")

    logger.info(f"  Successfully summarized {len(summaries)} pages")

    if not summaries:
        logger.error("No pages were successfully summarized.")
        close_browser()
        sys.exit(1)

    # Phase 4: Generate review
    logger.info("Phase 4: Generating review...")
    review_html = generate_review(topic, summaries)

    # Generate report
    path = generate_html_report(topic, review_html, all_urls, output_path)
    logger.info(f"Report saved to: {path}")

    close_browser()
    return path


def main():
    parser = argparse.ArgumentParser(
        description="Research Flow - Automated technical research assistant"
    )
    parser.add_argument("topic", help="Research topic or question")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help=f"Maximum pages to read (default: {DEFAULT_MAX_PAGES})",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output HTML file path (default: output/report_<timestamp>.html)",
    )

    args = parser.parse_args()

    if args.output is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"{DEFAULT_OUTPUT_DIR}/report_{timestamp}.html"

    logger.info(f"Starting research: {args.topic}")
    logger.info(f"Max pages: {args.max_pages}")
    logger.info(f"Output: {args.output}")

    try:
        path = run_research(args.topic, args.max_pages, args.output)
        print(f"\nDone! Report saved to: {path}")
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
        close_browser()
        sys.exit(1)
    except Exception as e:
        logger.error(f"Research failed: {e}")
        close_browser()
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify syntax**

```bash
python -c "import main; print('main.py OK')"
```

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: add main.py entry point with full research flow"
```

---

### Task 6: End-to-End Verification

**Files:**
- None (testing only)

- [ ] **Step 1: Install dependencies**

```bash
pip install -r requirements.txt
```

- [ ] **Step 2: Verify agent-browser is installed**

```bash
agent-browser --version
```

Expected: version number output. If not found, install with `npm install -g agent-browser && agent-browser install`.

- [ ] **Step 3: Set environment variable**

```bash
export OPENAI_API_KEY="sk-your-key-here"
```

- [ ] **Step 4: Run a quick test**

```bash
python main.py "What is Bun JavaScript runtime" --max-pages 5
```

Expected: Script runs through all 4 phases, generates an HTML report in `output/`.

- [ ] **Step 5: Open the report in browser**

```bash
# Find the generated file
ls -la output/
# Open it (macOS)
open output/report_*.html
# Or on Linux
xdg-open output/report_*.html
```

Expected: A styled HTML page with research summary, analysis, and source links.

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "feat: complete research-flow MVP"
```
