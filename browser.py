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
