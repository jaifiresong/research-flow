from mcp.server.fastmcp import FastMCP
# 注册当前目录到python 环境变量
import sys

sys.path.append(sys.path[0])

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

_LANGCHAIN_TOOLS = [
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
]

for t in _LANGCHAIN_TOOLS:
    mcp.add_tool(t.coroutine, name=t.name, description=t.description)

if __name__ == '__main__':
    mcp.run("stdio")
