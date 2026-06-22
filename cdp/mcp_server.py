#!/usr/bin/env python3
"""CDP 浏览器自动化 MCP Server。

通过 Model Context Protocol (stdio JSON-RPC) 暴露 BrowserTools 的所有工具，
供 Claude Desktop、Codex 等 MCP 客户端调用。

Usage:
    python mcp_server.py [--host HOST] [--port PORT]

    # 或通过 uv:
    uv run python mcp_server.py

    在 MCP 客户端配置中:
    {
        "mcpServers": {
            "cdp_driver": {
                "command": "python",
                "args": ["/path/to/cdp_driver/mcp_server.py", "--host", "127.0.0.1", "--port", "9222"]
            }
        }
    }
"""

import argparse
import asyncio
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from tools import BrowserTools  # noqa: E402

VERSION = '1.0.0'
PROTOCOL_VERSION = '2024-11-05'


def log(msg: str) -> None:
    """输出日志到 stderr（stdout 用于 MCP 协议通信）"""
    print(f'[cdp_driver:mcp] {msg}', file=sys.stderr, flush=True)


class MCPServer:
    """MCP JSON-RPC stdio 服务"""

    def __init__(self, host: str = '127.0.0.1', port: int = 9222):
        self._host = host
        self._port = port
        self._tools = BrowserTools()
        self._initialized = False
        self._reader_task: asyncio.Task | None = None

    async def start(self) -> None:
        """启动服务：连接 Chrome，注册工具，开始读取请求"""
        log(f'正在连接 Chrome DevTools ({self._host}:{self._port})...')
        await self._tools.connect(host=self._host, port=self._port)
        log(f'已连接。注册了 {len(list(self._tools._get_tool_methods()))} 个工具')

        loop = asyncio.get_running_loop()
        self._reader_task = asyncio.ensure_future(self._read_loop())

    async def _read_loop(self) -> None:
        """从 stdin 逐行读取 JSON-RPC 请求，分发处理"""
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        while True:
            try:
                raw = await reader.readline()
            except Exception:
                log('stdin 读取异常，退出')
                break

            if not raw:  # EOF
                log('stdin 已关闭')
                break

            line = raw.decode('utf-8').strip()
            if not line:
                continue

            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                log(f'无效 JSON: {line[:100]}')
                continue

            response = await self._handle_request(request)
            if response is not None:
                self._write(response)

    def _write(self, msg: dict) -> None:
        """写 JSON-RPC 响应到 stdout"""
        stdout = sys.stdout.buffer
        stdout.write(json.dumps(msg, ensure_ascii=False).encode('utf-8'))
        stdout.write(b'\n')
        stdout.flush()

    async def _handle_request(self, request: dict) -> dict | None:
        """路由 JSON-RPC 请求并返回响应。通知类请求返回 None。"""
        method = request.get('method', '')
        req_id = request.get('id')
        params = request.get('params', {})

        try:
            if method == 'initialize':
                return self._respond(req_id, {
                    'protocolVersion': PROTOCOL_VERSION,
                    'capabilities': {
                        'tools': {},
                    },
                    'serverInfo': {
                        'name': 'cdp_driver',
                        'version': VERSION,
                    },
                })

            if method == 'notifications/initialized':
                self._initialized = True
                log('MCP 握手完成')
                return None

            if method == 'ping':
                return self._respond(req_id, {})

            if method == 'tools/list':
                return self._respond(req_id, {
                    'tools': self._tools.schemas,
                })

            if method == 'tools/call':
                tool_name = params.get('name', '')
                arguments = params.get('arguments', {})
                log(f'调用工具: {tool_name}({arguments})')

                try:
                    result = await self._tools.call(tool_name, **arguments)
                except Exception as e:
                    log(f'工具调用失败: {e}')
                    return self._error(req_id, -32000, str(e))

                content = self._format_result(tool_name, result)
                return self._respond(req_id, {'content': content})

            # 未知方法
            return self._error(req_id, -32601, f'未知方法: {method}')

        except Exception as e:
            log(f'处理请求异常: {traceback.format_exc()}')
            return self._error(req_id, -32603, f'内部错误: {e}')

    def _format_result(self, tool_name: str, result: str) -> list[dict]:
        """将工具返回值格式化为 MCP content 列表"""
        if tool_name == 'screenshot':
            return [
                {'type': 'image', 'data': result, 'mimeType': 'image/png'},
                {'type': 'text', 'text': '截图完成'},
            ]
        return [{'type': 'text', 'text': result}]

    @staticmethod
    def _respond(req_id, result: dict) -> dict:
        return {'jsonrpc': '2.0', 'id': req_id, 'result': result}

    @staticmethod
    def _error(req_id, code: int, message: str) -> dict:
        return {'jsonrpc': '2.0', 'id': req_id, 'error': {'code': code, 'message': message}}

    async def shutdown(self) -> None:
        """关闭服务"""
        log('正在关闭...')
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        await self._tools.close()


def main():
    parser = argparse.ArgumentParser(description='CDP 浏览器自动化 MCP Server')
    parser.add_argument('--host', default='127.0.0.1', help='Chrome DevTools 主机地址')
    parser.add_argument('--port', type=int, default=9222, help='Chrome DevTools 端口号')
    args = parser.parse_args()

    server = MCPServer(host=args.host, port=args.port)

    async def run():
        try:
            await server.start()
            await asyncio.Event().wait()  # 永久等待，直到被中断
        except asyncio.CancelledError:
            pass
        except Exception:
            log(traceback.format_exc())
        finally:
            await server.shutdown()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log('收到中断信号')


if __name__ == '__main__':
    main()
