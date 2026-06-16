"""LangChain tools for browser automation via CDP."""
import asyncio
from typing import Optional

from langchain.tools import tool

from cdp.browser import Browser


_browser: Optional[Browser] = None


def get_browser() -> Browser:
    """Get or create the global Browser instance."""
    global _browser
    if _browser is None:
        _browser = Browser(port=9222)
    return _browser


async def ensure_started() -> None:
    b = get_browser()
    if b._cdp is None:
        await b.start()


@tool
async def browser_open(url: str, wait: float = 3.0) -> str:
    """Navigate the browser to a URL and wait for the page to load.

    Args:
        url: The full URL to navigate to (e.g. https://example.com).
        wait: Seconds to wait for SPA content to render (default 3.0).
    """
    await ensure_started()
    b = get_browser()
    await b.open(url, spa_wait=wait)
    return f"Opened {await b.url()} — title: {await b.title()}"


@tool
async def browser_snapshot() -> str:
    """Capture an accessibility snapshot of the current page.

    Returns a list of interactive elements (links, buttons, inputs, etc.)
    each prefixed with a reference like @e1, @e2 that can be used
    with click and fill tools.
    """
    await ensure_started()
    return await get_browser().snapshot()


@tool
async def browser_click(ref: str) -> str:
    """Click an interactive element on the page.

    Args:
        ref: Element reference from snapshot (e.g. @e1, @e42).
    """
    await ensure_started()
    b = get_browser()
    await b.click(ref)
    return f"Clicked {ref} — current URL: {await b.url()}, title: {await b.title()}"


@tool
async def browser_fill(ref: str, text: str) -> str:
    """Fill text into an input element or select an option from a dropdown.

    Args:
        ref: Element reference from snapshot (e.g. @e1).
        text: Text to type into the field or option text to select.
    """
    await ensure_started()
    b = get_browser()
    await b.fill(ref, text)
    return f"Filled {ref} with: {text}"


@tool
async def browser_type(ref: str, text: str) -> str:
    """Alias for browser_fill — type text into an input element.

    Args:
        ref: Element reference from snapshot (e.g. @e1).
        text: Text to type into the field.
    """
    await ensure_started()
    b = get_browser()
    await b.type(ref, text)
    return f"Typed into {ref}: {text}"


@tool
async def browser_evaluate(js: str) -> str:
    """Execute JavaScript in the page and return the result.

    Args:
        js: JavaScript expression to evaluate (e.g. 'document.title').
    """
    await ensure_started()
    result = await get_browser().evaluate(js)
    return str(result) if result is not None else "null"


@tool
async def browser_title() -> str:
    """Get the current page title."""
    await ensure_started()
    return await get_browser().title()


@tool
async def browser_current_url() -> str:
    """Get the current page URL."""
    await ensure_started()
    return await get_browser().url()


@tool
async def browser_wait(seconds: float = 2.0) -> str:
    """Wait for a number of seconds (useful after page interactions).

    Args:
        seconds: Number of seconds to wait (default 2.0).
    """
    await asyncio.sleep(seconds)
    return f"Waited {seconds}s"


@tool
async def browser_close() -> str:
    """Close the browser and disconnect from CDP.

    Call this when you are done with browser automation.
    """
    global _browser
    if _browser is not None:
        b = _browser
        _browser = None
        await b.close()
    return "Browser closed"


BROWSER_TOOLS = [
    browser_open,
    browser_snapshot,
    browser_click,
    browser_fill,
    browser_type,
    browser_evaluate,
    browser_title,
    browser_current_url,
    browser_wait,
    browser_close,
]
