from mcp.server.fastmcp import FastMCP

from tools import (
    browser_open,
    browser_snapshot,
    browser_extract,
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
)

mcp = FastMCP("基于CDP操作浏览器")
mcp.add_tool(browser_open)
mcp.add_tool(browser_snapshot)
mcp.add_tool(browser_extract)
mcp.add_tool(browser_click)
mcp.add_tool(browser_fill)
mcp.add_tool(browser_type)
mcp.add_tool(browser_scroll)
mcp.add_tool(browser_scroll_to_bottom)
mcp.add_tool(browser_scroll_into_view)
mcp.add_tool(browser_evaluate)
mcp.add_tool(browser_title)
mcp.add_tool(browser_current_url)
mcp.add_tool(browser_wait)
mcp.add_tool(browser_close)

if __name__ == '__main__':
    mcp.run("stdio")
