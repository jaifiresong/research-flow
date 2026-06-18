"""MCP 服务测试脚本 — 使用 mcp.client.stdio 官方 SDK。

相比手动 JSON-RPC 的改进：
- 解决 subprocess.PIPE stderr 管道缓冲区死锁
- 解决 stdout.readline() 永久阻塞（搭配 asyncio.wait_for 超时）
- 解决手动解析时消息 id 未对齐、通知行干扰等问题
"""
import asyncio
import sys
import time
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def main():
    script_path = Path(__file__).parent / "tools_mcp_server.py"
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[str(script_path)],
        cwd=str(script_path.parent),
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("MCP 服务已启动，输入工具调用（格式：name key1===val1 key2===val2）")
            print('输入 "quit" 或 Ctrl+C 退出\n')

            while True:
                try:
                    data = await asyncio.to_thread(input, ">>> ")
                except EOFError:
                    break
                data = data.strip()
                if not data or data in ("quit", "exit"):
                    break

                parts = data.split()
                name = parts[0]
                kwargs = {}
                for p in parts[1:]:
                    if "===" not in p:
                        continue
                    k, v = p.split("===", 1)
                    try:
                        v = float(v) if "." in v else int(v)
                    except ValueError:
                        v = v.strip("\"'")
                    kwargs[k] = v

                t0 = time.monotonic()
                try:
                    result = await asyncio.wait_for(
                        session.call_tool(name, kwargs),
                        timeout=15.0,
                    )
                    elapsed = time.monotonic() - t0
                    text = "".join(
                        getattr(c, "text", "") for c in result.content
                    )
                    print(f"[{elapsed:.1f}s] {text}")
                except asyncio.TimeoutError:
                    print(f"[TIMEOUT] {name} 调用超时 (>15s)，服务端可能因页面阻塞或断连无响应")
                except Exception as e:
                    print(f"[ERROR] {name}: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print()
