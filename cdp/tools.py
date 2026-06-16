"""LangChain tools for browser automation via CDP."""
import asyncio
import functools
import logging
import time
from pathlib import Path
from typing import Optional

from langchain.tools import tool

from cdp.browser import Browser

# ── 日志（仅输出到文件，不输出控制台） ──

_tool_logger = logging.getLogger("cdp.tools")
_tool_logger.setLevel(logging.DEBUG)
_tool_logger.propagate = False  # 不传递给 root logger，避免输出到控制台

_log_path = Path(__file__).parent.parent / "logs/tool_calls.log"
_handler = logging.FileHandler(str(_log_path), encoding="utf-8")
_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))
_tool_logger.addHandler(_handler)


def log_tool_call(func):
    """装饰器：记录工具调用的参数、返回值、耗时和异常到文件日志。"""

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        t0 = time.monotonic()
        try:
            result = await func(*args, **kwargs)
            elapsed = time.monotonic() - t0
            _tool_logger.info(
                "[%s] args=%s kwargs=%s → %.3fs → %s",
                func.__name__, args, kwargs, elapsed,
                str(result)[:300],
            )
            return result
        except Exception as exc:
            elapsed = time.monotonic() - t0
            _tool_logger.error(
                "[%s] args=%s kwargs=%s → %.3fs → ERROR: %s",
                func.__name__, args, kwargs, elapsed, exc,
            )
            raise

    return wrapper


# ── 浏览器实例管理 ──

_browser: Optional[Browser] = None


def get_browser() -> Browser:
    """获取或创建全局浏览器实例。"""
    global _browser
    if _browser is None:
        _browser = Browser(port=9222)
    return _browser


async def ensure_started() -> None:
    """确保浏览器已启动并连接。"""
    b = get_browser()
    if b._cdp is None:
        await b.start()


# ── 浏览器工具 ──


@tool
@log_tool_call
async def browser_open(url: str, wait: float = 3.0) -> str:
    """导航到指定 URL 并等待页面加载。

    Args:
        url: 完整的 URL 地址（例如 https://example.com）。
        wait: SPA 页面渲染等待秒数（默认 3.0）。
    """
    await ensure_started()
    b = get_browser()
    await b.open(url, spa_wait=wait)
    return f"已打开 {await b.url()} — 标题: {await b.title()}"


@tool
@log_tool_call
async def browser_snapshot() -> str:
    """获取当前页面的可访问性快照。

    返回所有可交互元素（链接、按钮、输入框等），每个元素前有引用标记如 @e1、@e2，
    可供 click / fill 工具使用。
    """
    await ensure_started()
    return await get_browser().snapshot()


@tool
@log_tool_call
async def browser_click(ref: str) -> str:
    """点击页面上的可交互元素。

    Args:
        ref: 快照中的元素引用（例如 @e1、@e42）。
    """
    await ensure_started()
    b = get_browser()
    await b.click(ref)
    return f"已点击 {ref} — 当前 URL: {await b.url()}, 标题: {await b.title()}"


@tool
@log_tool_call
async def browser_fill(ref: str, text: str) -> str:
    """向输入框填入文本或在下拉菜单中选择选项。

    Args:
        ref: 快照中的元素引用（例如 @e1）。
        text: 要填入的文本，或要匹配的下拉选项文本。
    """
    await ensure_started()
    b = get_browser()
    await b.fill(ref, text)
    return f"已填入 {ref}: {text}"


@tool
@log_tool_call
async def browser_type(ref: str, text: str) -> str:
    """browser_fill 的别名 —— 向输入框输入文本。

    Args:
        ref: 快照中的元素引用（例如 @e1）。
        text: 要输入的文本。
    """
    await ensure_started()
    b = get_browser()
    await b.type(ref, text)
    return f"已输入 {ref}: {text}"


@tool
@log_tool_call
async def browser_evaluate(js: str) -> str:
    """在页面中执行 JavaScript 并返回结果。

    Args:
        js: 要执行的 JavaScript 表达式（例如 'document.title'）。
    """
    await ensure_started()
    result = await get_browser().evaluate(js)
    return str(result) if result is not None else "null"


@tool
@log_tool_call
async def browser_title() -> str:
    """获取当前页面的标题。"""
    await ensure_started()
    return await get_browser().title()


@tool
@log_tool_call
async def browser_current_url() -> str:
    """获取当前页面的 URL。"""
    await ensure_started()
    return await get_browser().url()


@tool
@log_tool_call
async def browser_wait(seconds: float = 2.0) -> str:
    """等待指定秒数（用于等待页面渲染或动画完成）。

    Args:
        seconds: 等待秒数（默认 2.0）。
    """
    await asyncio.sleep(seconds)
    return f"已等待 {seconds}s"


@tool
@log_tool_call
async def browser_scroll(direction: str = "down", amount: float = 300, ref: str = "") -> str:
    """按方向滚动页面或指定元素。

    Args:
        direction: 滚动方向，可选值：'up'（上）、'down'（下，默认）、'left'（左）、'right'（右）。
        amount: 滚动像素数（默认 300）。想一次滚到底可以传大值如 99999。
        ref: 可选，元素引用（如 @e1）。传入时滚动该元素内部，否则滚动整个页面。
    """
    await ensure_started()
    b = get_browser()
    r = ref if ref else None
    await b.scroll(direction=direction, amount=amount, ref=r)
    return f"已向 {direction} 滚动 {amount}px" + (f"（元素 {ref} 内）" if ref else "")


@tool
@log_tool_call
async def browser_scroll_to_bottom() -> str:
    """滚动页面到底部。"""
    await ensure_started()
    await get_browser().scroll_to_bottom()
    return "已滚动到页面底部"


@tool
@log_tool_call
async def browser_scroll_into_view(ref: str) -> str:
    """将指定元素滚动到可视区域中央。

    Args:
        ref: 快照中的元素引用（例如 @e1）。
    """
    await ensure_started()
    await get_browser().scroll_into_view(ref)
    return f"已将 {ref} 滚动到可视区域"


@tool
@log_tool_call
async def browser_close() -> str:
    """关闭浏览器并断开 CDP 连接。

    完成浏览器自动化后调用此工具。
    """
    global _browser
    if _browser is not None:
        b = _browser
        _browser = None
        await b.close()
    return "浏览器已关闭"


BROWSER_TOOLS = [
    browser_open,
    browser_snapshot,
    browser_click,
    browser_fill,
    browser_type,
    browser_scroll,
    browser_scroll_to_bottom,
    browser_scroll_into_view,
    browser_evaluate,
    browser_title,
    browser_current_url,
    browser_wait,
    browser_close,
]
