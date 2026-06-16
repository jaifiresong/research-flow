import subprocess
import logging
import re
from typing import Optional

from langchain.tools import tool

from config import AGENT_BROWSER_PATH

logger = logging.getLogger(__name__)


# ── Browser Class ───────────────────────────────────────────────────

class Browser:
    """Class-based wrapper around the agent-browser CLI.

    Supports specifying a CDP port to connect to an existing browser,
    or launching a new browser session.

    Usage:
        # Launch new browser
        with Browser() as browser:
            browser.open("https://example.com")
            text = browser.get_text("body")

        # Connect via CDP port
        with Browser(cdp_port=9222) as browser:
            browser.open("https://example.com")
    """

    def __init__(
        self,
        cdp_port: Optional[int] = None,
        cdp_url: Optional[str] = None,
        session: Optional[str] = None,
        headed: bool = False,
        executable_path: Optional[str] = None,
    ):
        self._cdp_port = cdp_port
        self._cdp_url = cdp_url
        self._session = session
        self._headed = headed
        self._executable_path = executable_path
        self._connected = False

    def _build_global_args(self) -> list[str]:
        args = []
        if self._cdp_port:
            args += ["--cdp", str(self._cdp_port)]
        elif self._cdp_url:
            args += ["--cdp", self._cdp_url]
        if self._session:
            args += ["--session", self._session]
        if self._headed:
            args.append("--headed")
        if self._executable_path:
            args += ["--executable-path", self._executable_path]
        return args

    def run(self, args: list[str], timeout: int = 30) -> Optional[str]:
        """Run an agent-browser command and return stdout, or None on failure."""
        cmd = [AGENT_BROWSER_PATH] + self._build_global_args() + args
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
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

    # ── Navigation ──────────────────────────────────────────────────

    def open(self, url: str) -> bool:
        return self.run(["open", url], timeout=30) is not None

    def back(self) -> bool:
        return self.run(["back"]) is not None

    def forward(self) -> bool:
        return self.run(["forward"]) is not None

    def reload(self) -> bool:
        return self.run(["reload"]) is not None

    # ── Interaction ─────────────────────────────────────────────────

    def click(self, selector: str) -> bool:
        return self.run(["click", selector]) is not None

    def dblclick(self, selector: str) -> bool:
        return self.run(["dblclick", selector]) is not None

    def fill(self, selector: str, text: str) -> bool:
        return self.run(["fill", selector, text]) is not None

    def type_text(self, selector: str, text: str) -> bool:
        return self.run(["type", selector, text]) is not None

    def press(self, key: str) -> bool:
        return self.run(["press", key]) is not None

    def hover(self, selector: str) -> bool:
        return self.run(["hover", selector]) is not None

    def select(self, selector: str, value: str) -> bool:
        return self.run(["select", selector, value]) is not None

    def check(self, selector: str) -> bool:
        return self.run(["check", selector]) is not None

    def uncheck(self, selector: str) -> bool:
        return self.run(["uncheck", selector]) is not None

    def focus(self, selector: str) -> bool:
        return self.run(["focus", selector]) is not None

    def scroll(self, direction: str, pixels: Optional[int] = None) -> bool:
        args = ["scroll", direction]
        if pixels is not None:
            args.append(str(pixels))
        return self.run(args) is not None

    def scroll_into_view(self, selector: str) -> bool:
        return self.run(["scrollintoview", selector]) is not None

    def drag(self, source: str, target: str) -> bool:
        return self.run(["drag", source, target]) is not None

    def upload(self, selector: str, files: list[str]) -> bool:
        return self.run(["upload", selector] + files) is not None

    # ── Get Info ────────────────────────────────────────────────────

    def get_text(self, selector: str) -> Optional[str]:
        return self.run(["get", "text", selector], timeout=15)

    def get_html(self, selector: str) -> Optional[str]:
        return self.run(["get", "html", selector], timeout=15)

    def get_value(self, selector: str) -> Optional[str]:
        return self.run(["get", "value", selector], timeout=15)

    def get_attr(self, selector: str, attr: str) -> Optional[str]:
        return self.run(["get", "attr", selector, attr], timeout=15)

    def get_title(self) -> Optional[str]:
        return self.run(["get", "title"], timeout=10)

    def get_url(self) -> Optional[str]:
        return self.run(["get", "url"], timeout=10)

    def get_count(self, selector: str) -> Optional[str]:
        return self.run(["get", "count", selector], timeout=10)

    # ── Check State ─────────────────────────────────────────────────

    def is_visible(self, selector: str) -> bool:
        result = self.run(["is", "visible", selector], timeout=10)
        return result is not None and "true" in result.lower()

    def is_enabled(self, selector: str) -> bool:
        result = self.run(["is", "enabled", selector], timeout=10)
        return result is not None and "true" in result.lower()

    def is_checked(self, selector: str) -> bool:
        result = self.run(["is", "checked", selector], timeout=10)
        return result is not None and "true" in result.lower()

    # ── Snapshot & Screenshot ───────────────────────────────────────

    def snapshot(self, interactive: bool = False, urls: bool = False,
                 compact: bool = False, depth: Optional[int] = None,
                 selector: Optional[str] = None) -> Optional[str]:
        args = ["snapshot"]
        if interactive:
            args.append("-i")
        if urls:
            args.append("--urls")
        if compact:
            args.append("-c")
        if depth is not None:
            args += ["-d", str(depth)]
        if selector:
            args += ["-s", selector]
        return self.run(args, timeout=15)

    def screenshot(self, path: Optional[str] = None, full: bool = False,
                   annotate: bool = False) -> Optional[str]:
        args = ["screenshot"]
        if full:
            args.append("--full")
        if annotate:
            args.append("--annotate")
        if path:
            args.append(path)
        return self.run(args, timeout=30)

    def pdf(self, path: str) -> bool:
        return self.run(["pdf", path], timeout=30) is not None

    # ── Wait ────────────────────────────────────────────────────────

    def wait(self, selector_or_ms: Optional[str] = None, *,
             text: Optional[str] = None, url: Optional[str] = None,
             load: Optional[str] = None, fn: Optional[str] = None) -> bool:
        args = ["wait"]
        if selector_or_ms:
            args.append(selector_or_ms)
        if text:
            args += ["--text", text]
        if url:
            args += ["--url", url]
        if load:
            args += ["--load", load]
        if fn:
            args += ["--fn", fn]
        return self.run(args, timeout=60) is not None

    # ── JavaScript ──────────────────────────────────────────────────

    def eval(self, js: str) -> Optional[str]:
        return self.run(["eval", js], timeout=15)

    # ── Find (Semantic Locators) ────────────────────────────────────

    def find(self, locator_type: str, locator_value: str,
             action: str, value: Optional[str] = None,
             name: Optional[str] = None) -> Optional[str]:
        args = ["find", locator_type, locator_value, action]
        if value:
            args.append(value)
        if name:
            args += ["--name", name]
        return self.run(args, timeout=15)

    # ── Tabs ────────────────────────────────────────────────────────

    def tab_list(self) -> Optional[str]:
        return self.run(["tab"], timeout=10)

    def tab_new(self, url: Optional[str] = None, label: Optional[str] = None) -> Optional[str]:
        args = ["tab", "new"]
        if label:
            args += ["--label", label]
        if url:
            args.append(url)
        return self.run(args, timeout=15)

    def tab_switch(self, tab_id_or_label: str) -> bool:
        return self.run(["tab", tab_id_or_label]) is not None

    def tab_close(self, tab_id_or_label: Optional[str] = None) -> bool:
        args = ["tab", "close"]
        if tab_id_or_label:
            args.append(tab_id_or_label)
        return self.run(args) is not None

    # ── Cookies & Storage ───────────────────────────────────────────

    def cookies_get(self) -> Optional[str]:
        return self.run(["cookies"], timeout=10)

    def cookies_set(self, name: str, value: str) -> bool:
        return self.run(["cookies", "set", name, value]) is not None

    def cookies_clear(self) -> bool:
        return self.run(["cookies", "clear"]) is not None

    def storage_local_get(self, key: Optional[str] = None) -> Optional[str]:
        args = ["storage", "local"]
        if key:
            args.append(key)
        return self.run(args, timeout=10)

    def storage_local_set(self, key: str, value: str) -> bool:
        return self.run(["storage", "local", "set", key, value]) is not None

    def storage_local_clear(self) -> bool:
        return self.run(["storage", "local", "clear"]) is not None

    # ── Network ─────────────────────────────────────────────────────

    def network_requests(self, filter_text: Optional[str] = None,
                         req_type: Optional[str] = None) -> Optional[str]:
        args = ["network", "requests"]
        if filter_text:
            args += ["--filter", filter_text]
        if req_type:
            args += ["--type", req_type]
        return self.run(args, timeout=10)

    def network_route(self, url: str, *, abort: bool = False,
                      body: Optional[str] = None) -> bool:
        args = ["network", "route", url]
        if abort:
            args.append("--abort")
        if body:
            args += ["--body", body]
        return self.run(args) is not None

    def network_unroute(self, url: Optional[str] = None) -> bool:
        args = ["network", "unroute"]
        if url:
            args.append(url)
        return self.run(args) is not None

    # ── Dialogs ─────────────────────────────────────────────────────

    def dialog_accept(self, text: Optional[str] = None) -> bool:
        args = ["dialog", "accept"]
        if text:
            args.append(text)
        return self.run(args) is not None

    def dialog_dismiss(self) -> bool:
        return self.run(["dialog", "dismiss"]) is not None

    # ── Settings ────────────────────────────────────────────────────

    def set_viewport(self, width: int, height: int) -> bool:
        return self.run(["set", "viewport", str(width), str(height)]) is not None

    def set_headers(self, headers_json: str) -> bool:
        return self.run(["set", "headers", headers_json]) is not None

    def set_offline(self, on: bool = True) -> bool:
        val = "on" if on else "off"
        return self.run(["set", "offline", val]) is not None

    # ── State ───────────────────────────────────────────────────────

    def state_save(self, path: str) -> bool:
        return self.run(["state", "save", path]) is not None

    def state_load(self, path: str) -> bool:
        return self.run(["state", "load", path]) is not None

    # ── Console & Debug ─────────────────────────────────────────────

    def console(self, clear: bool = False) -> Optional[str]:
        args = ["console"]
        if clear:
            args.append("--clear")
        return self.run(args, timeout=10)

    def errors(self, clear: bool = False) -> Optional[str]:
        args = ["errors"]
        if clear:
            args.append("--clear")
        return self.run(args, timeout=10)

    # ── Lifecycle ───────────────────────────────────────────────────

    def connect(self) -> bool:
        """Connect to browser (launch or CDP)."""
        if self._cdp_port or self._cdp_url:
            result = self.run(["connect", str(self._cdp_port or self._cdp_url)], timeout=15)
        else:
            result = self.run(["open"], timeout=15)
        self._connected = result is not None
        return self._connected

    def close(self) -> None:
        self.run(["close"], timeout=10)
        self._connected = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


# ── Global Browser Instance for Tools ───────────────────────────────

_browser: Optional[Browser] = None


def _get_browser() -> Browser:
    global _browser
    if _browser is None:
        _browser = Browser()
    return _browser


# ── LangChain Tools ─────────────────────────────────────────────────

@tool
def browser_connect(cdp_port: int = 0) -> str:
    """Connect to a browser. Pass cdp_port to connect to an existing Chrome via CDP (e.g. 9222). Pass 0 to launch a new browser."""
    global _browser
    if cdp_port > 0:
        _browser = Browser(cdp_port=cdp_port)
    else:
        _browser = Browser()
    ok = _browser.connect()
    return "connected" if ok else "failed"


@tool
def browser_disconnect() -> str:
    """Close the browser and disconnect."""
    global _browser
    if _browser:
        _browser.close()
        _browser = None
    return "disconnected"


@tool
def browser_open(url: str) -> str:
    """Open a URL in the browser. Example: browser_open("https://example.com")"""
    ok = _get_browser().open(url)
    return "success" if ok else "failed"


@tool
def browser_back() -> str:
    """Navigate back in browser history."""
    ok = _get_browser().back()
    return "success" if ok else "failed"


@tool
def browser_forward() -> str:
    """Navigate forward in browser history."""
    ok = _get_browser().forward()
    return "success" if ok else "failed"


@tool
def browser_reload() -> str:
    """Reload the current page."""
    ok = _get_browser().reload()
    return "success" if ok else "failed"


@tool
def browser_click(selector: str) -> str:
    """Click an element by CSS selector or ref. Example: browser_click("@e2") or browser_click("#submit")"""
    ok = _get_browser().click(selector)
    return "success" if ok else "failed"


@tool
def browser_dblclick(selector: str) -> str:
    """Double-click an element."""
    ok = _get_browser().dblclick(selector)
    return "success" if ok else "failed"


@tool
def browser_fill(selector: str, text: str) -> str:
    """Clear an input field and fill it with text. Example: browser_fill("#email", "test@test.com")"""
    ok = _get_browser().fill(selector, text)
    return "success" if ok else "failed"


@tool
def browser_type(selector: str, text: str) -> str:
    """Type text into an element without clearing it first."""
    ok = _get_browser().type_text(selector, text)
    return "success" if ok else "failed"


@tool
def browser_press(key: str) -> str:
    """Press a keyboard key. Examples: "Enter", "Tab", "Escape", "Control+a" """
    ok = _get_browser().press(key)
    return "success" if ok else "failed"


@tool
def browser_hover(selector: str) -> str:
    """Hover over an element."""
    ok = _get_browser().hover(selector)
    return "success" if ok else "failed"


@tool
def browser_select(selector: str, value: str) -> str:
    """Select an option from a dropdown. Example: browser_select("select#country", "US")"""
    ok = _get_browser().select(selector, value)
    return "success" if ok else "failed"


@tool
def browser_check(selector: str) -> str:
    """Check a checkbox."""
    ok = _get_browser().check(selector)
    return "success" if ok else "failed"


@tool
def browser_uncheck(selector: str) -> str:
    """Uncheck a checkbox."""
    ok = _get_browser().uncheck(selector)
    return "success" if ok else "failed"


@tool
def browser_scroll(direction: str, pixels: int = 300) -> str:
    """Scroll the page. direction: "up", "down", "left", "right". Example: browser_scroll("down", 500)"""
    ok = _get_browser().scroll(direction, pixels)
    return "success" if ok else "failed"


@tool
def browser_scroll_into_view(selector: str) -> str:
    """Scroll an element into view."""
    ok = _get_browser().scroll_into_view(selector)
    return "success" if ok else "failed"


@tool
def browser_snapshot(interactive: bool = False, urls: bool = False,
                     compact: bool = False, depth: int = 0) -> str:
    """Get accessibility tree snapshot of the current page. Use interactive=True to only show interactive elements (buttons, links, inputs). Use urls=True to include link URLs."""
    b = _get_browser()
    result = b.snapshot(
        interactive=interactive,
        urls=urls,
        compact=compact,
        depth=depth if depth > 0 else None,
    )
    return result or "failed"


@tool
def browser_screenshot(path: str = "", full: bool = False, annotate: bool = False) -> str:
    """Take a screenshot. Set annotate=True to get numbered element labels. Set full=True for full page."""
    b = _get_browser()
    result = b.screenshot(path=path or None, full=full, annotate=annotate)
    return result or "failed"


@tool
def browser_get_text(selector: str) -> str:
    """Get the text content of an element. Use "body" for full page text."""
    result = _get_browser().get_text(selector)
    return result or "no text found"


@tool
def browser_get_html(selector: str) -> str:
    """Get the innerHTML of an element."""
    result = _get_browser().get_html(selector)
    return result or "no html found"


@tool
def browser_get_value(selector: str) -> str:
    """Get the value of an input element."""
    result = _get_browser().get_value(selector)
    return result or ""


@tool
def browser_get_attr(selector: str, attr: str) -> str:
    """Get an attribute of an element. Example: browser_get_attr("a.link", "href")"""
    result = _get_browser().get_attr(selector, attr)
    return result or ""


@tool
def browser_get_title() -> str:
    """Get the page title."""
    result = _get_browser().get_title()
    return result or ""


@tool
def browser_get_url() -> str:
    """Get the current page URL."""
    result = _get_browser().get_url()
    return result or ""


@tool
def browser_get_count(selector: str) -> str:
    """Count elements matching a CSS selector."""
    result = _get_browser().get_count(selector)
    return result or "0"


@tool
def browser_is_visible(selector: str) -> str:
    """Check if an element is visible. Returns "true" or "false"."""
    return "true" if _get_browser().is_visible(selector) else "false"


@tool
def browser_is_enabled(selector: str) -> str:
    """Check if an element is enabled. Returns "true" or "false"."""
    return "true" if _get_browser().is_enabled(selector) else "false"


@tool
def browser_is_checked(selector: str) -> str:
    """Check if a checkbox is checked. Returns "true" or "false"."""
    return "true" if _get_browser().is_checked(selector) else "false"


@tool
def browser_wait(selector_or_ms: str = "3000") -> str:
    """Wait for a selector to appear or for a duration in ms. Examples: browser_wait("#content"), browser_wait("3000")"""
    ok = _get_browser().wait(selector_or_ms)
    return "done" if ok else "failed"


@tool
def browser_wait_for_text(text: str) -> str:
    """Wait until specific text appears on the page. Example: browser_wait_for_text("Welcome")"""
    ok = _get_browser().wait(text=text)
    return "done" if ok else "failed"


@tool
def browser_wait_for_url(url_pattern: str) -> str:
    """Wait until the URL matches a pattern. Example: browser_wait_for_url("**/dashboard")"""
    ok = _get_browser().wait(url=url_pattern)
    return "done" if ok else "failed"


@tool
def browser_wait_for_load(state: str = "networkidle") -> str:
    """Wait for page load state. States: "load", "domcontentloaded", "networkidle" """
    ok = _get_browser().wait(load=state)
    return "done" if ok else "failed"


@tool
def browser_eval(js: str) -> str:
    """Execute JavaScript in the browser and return the result. Example: browser_eval("document.title")"""
    result = _get_browser().eval(js)
    return result or ""


@tool
def browser_find(locator_type: str, locator_value: str, action: str,
                 value: str = "", name: str = "") -> str:
    """Find element by semantic locator and perform action.
    locator_type: "role", "text", "label", "placeholder", "alt", "testid"
    action: "click", "fill", "type", "hover", "focus", "text"
    Example: browser_find("role", "button", "click", name="Submit")
    """
    result = _get_browser().find(
        locator_type, locator_value, action,
        value=value or None, name=name or None,
    )
    return result or "success" if action != "text" else (result or "not found")


@tool
def browser_tab_list() -> str:
    """List all open browser tabs."""
    result = _get_browser().tab_list()
    return result or "no tabs"


@tool
def browser_tab_new(url: str = "", label: str = "") -> str:
    """Open a new browser tab. Optionally navigate to a URL and/or assign a label."""
    result = _get_browser().tab_new(
        url=url or None, label=label or None,
    )
    return result or "failed"


@tool
def browser_tab_switch(tab_id_or_label: str) -> str:
    """Switch to a tab by id (e.g. "t1") or label (e.g. "docs")."""
    ok = _get_browser().tab_switch(tab_id_or_label)
    return "success" if ok else "failed"


@tool
def browser_tab_close(tab_id_or_label: str = "") -> str:
    """Close a tab. Closes active tab if no id specified."""
    ok = _get_browser().tab_close(tab_id_or_label or None)
    return "success" if ok else "failed"


@tool
def browser_cookies_get() -> str:
    """Get all cookies for the current page."""
    result = _get_browser().cookies_get()
    return result or "no cookies"


@tool
def browser_cookies_set(name: str, value: str) -> str:
    """Set a cookie."""
    ok = _get_browser().cookies_set(name, value)
    return "success" if ok else "failed"


@tool
def browser_cookies_clear() -> str:
    """Clear all cookies."""
    ok = _get_browser().cookies_clear()
    return "success" if ok else "failed"


@tool
def browser_network_requests(filter_text: str = "", req_type: str = "") -> str:
    """View tracked network requests. filter_text filters by URL, req_type filters by type (xhr, fetch, etc)."""
    result = _get_browser().network_requests(
        filter_text=filter_text or None,
        req_type=req_type or None,
    )
    return result or "no requests"


@tool
def browser_console(clear: bool = False) -> str:
    """View browser console messages (log, error, warn, info). Set clear=True to clear after reading."""
    result = _get_browser().console(clear=clear)
    return result or "no console messages"


@tool
def browser_errors(clear: bool = False) -> str:
    """View uncaught JavaScript page errors. Set clear=True to clear after reading."""
    result = _get_browser().errors(clear=clear)
    return result or "no errors"


@tool
def browser_set_viewport(width: int, height: int) -> str:
    """Set the browser viewport size. Example: browser_set_viewport(1920, 1080)"""
    ok = _get_browser().set_viewport(width, height)
    return "success" if ok else "failed"


@tool
def browser_set_offline(on: bool = True) -> str:
    """Toggle offline mode. on=True to go offline, on=False to go online."""
    ok = _get_browser().set_offline(on)
    return "success" if ok else "failed"


@tool
def browser_state_save(path: str) -> str:
    """Save browser auth state (cookies, localStorage) to a JSON file."""
    ok = _get_browser().state_save(path)
    return "success" if ok else "failed"


@tool
def browser_state_load(path: str) -> str:
    """Load browser auth state from a previously saved JSON file."""
    ok = _get_browser().state_load(path)
    return "success" if ok else "failed"


@tool
def browser_pdf(path: str) -> str:
    """Save the current page as a PDF. Example: browser_pdf("/tmp/page.pdf")"""
    ok = _get_browser().pdf(path)
    return "success" if ok else "failed"


@tool
def browser_highlight(selector: str) -> str:
    """Highlight an element on the page for debugging."""
    result = _get_browser().run(["highlight", selector])
    return "success" if result is not None else "failed"


@tool
def browser_focus(selector: str) -> str:
    """Focus an element."""
    ok = _get_browser().focus(selector)
    return "success" if ok else "failed"


# ── Backward-compatible module-level functions (for main.py) ────────

def open_url(url: str) -> bool:
    return _get_browser().open(url)

def get_page_text() -> Optional[str]:
    return _get_browser().get_text("body")

def get_snapshot() -> Optional[str]:
    return _get_browser().snapshot()

def search_google(query: str) -> Optional[str]:
    b = _get_browser()
    if not b.open("https://www.google.com"):
        return None
    fill_ok = b.fill("textarea[name='q']", query)
    if not fill_ok:
        fill_ok = b.fill("input[name='q']", query)
    if not fill_ok:
        logger.warning("Could not find Google search box")
        return None
    b.press("Enter")
    b.wait("3000")
    return b.snapshot()

def extract_urls_from_snapshot(snapshot: str, max_urls: int = 10) -> list[str]:
    urls = []
    url_pattern = re.compile(r'https?://[^\s\)\]"]+')
    for match in url_pattern.finditer(snapshot):
        url = match.group(0).rstrip('/')
        if "google.com" in url or "googleapis.com" in url:
            continue
        if url not in urls:
            urls.append(url)
        if len(urls) >= max_urls:
            break
    return urls

def close_browser():
    global _browser
    if _browser:
        _browser.close()
        _browser = None
