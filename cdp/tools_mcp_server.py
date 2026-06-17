from mcp.server.fastmcp import FastMCP
# 注册当前目录到python 环境变量
import sys

sys.path.append(sys.path[0])

from tools import BROWSER_TOOLS

mcp = FastMCP("基于CDP操作浏览器")

for t in BROWSER_TOOLS:
    mcp.add_tool(t.coroutine, name=t.name, description=t.description)

if __name__ == '__main__':
    mcp.run("stdio")
