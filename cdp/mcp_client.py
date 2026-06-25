#!/usr/bin/env python3
"""MCP 测试客户端 — 演示完整的 MCP 握手 + 工具调用流程"""

import asyncio, json, sys


class MCPClient:
    """stdio JSON-RPC MCP 客户端"""

    def __init__(self, server_cmd: list[str]):
        self._server_cmd = server_cmd
        self._proc: asyncio.subprocess.Process | None = None
        self._req_id = 0

    async def __aenter__(self):
        self._proc = await asyncio.create_subprocess_exec(
            *self._server_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return self

    async def __aexit__(self, *args):
        if self._proc:
            self._proc.kill()
            await self._proc.wait()

    async def _send(self, method: str, params: dict | None = None) -> dict:
        self._req_id += 1
        req = {'jsonrpc': '2.0', 'id': self._req_id, 'method': method}
        if params:
            req['params'] = params
        payload = json.dumps(req, ensure_ascii=False) + '\n'
        self._proc.stdin.write(payload.encode())
        await self._proc.stdin.drain()

        raw = await asyncio.wait_for(self._proc.stdout.readline(), timeout=5)
        return json.loads(raw.decode().strip())

    async def _notify(self, method: str, params: dict | None = None) -> None:
        req = {'jsonrpc': '2.0', 'method': method}
        if params:
            req['params'] = params
        payload = json.dumps(req, ensure_ascii=False) + '\n'
        self._proc.stdin.write(payload.encode())
        await self._proc.stdin.drain()

    async def initialize(self) -> dict:
        return await self._send('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {}})

    async def list_tools(self) -> list[dict]:
        resp = await self._send('tools/list')
        return resp.get('result', {}).get('tools', [])

    async def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        return await self._send('tools/call', {'name': name, 'arguments': arguments or {}})


async def main():
    if len(sys.argv) < 2:
        print('用法: python mcp_client.py <server_script>')
        sys.exit(1)

    server_cmd = [sys.executable, *sys.argv[1:]]
    print(f'连接 MCP 服务器: {" ".join(server_cmd)}\n')

    async with MCPClient(server_cmd) as client:
        # 1. 初始化握手
        print('=== 1. initialize ===')
        init_resp = await client.initialize()
        info = init_resp['result']['serverInfo']
        print(f'   server: {info["name"]} v{info["version"]}')
        print(f'   protocol: {init_resp["result"]["protocolVersion"]}')
        print(f'   capabilities: {init_resp["result"]["capabilities"]}\n')

        # 2. 发送 initialized 通知
        print('=== 2. notifications/initialized ===')
        await client._notify('notifications/initialized')
        print('   已发送\n')

        # 3. 列出工具
        print('=== 3. tools/list ===')
        tools = await client.list_tools()
        for t in tools:
            print(f'   - {t["name"]}: {t.get("description", "")}')
        print()

        # 4. 测试 greet 工具
        print('=== 4. tools/call greet ===')
        resp = await client.call_tool('greet', {'name': 'Alice'})
        _show(resp, 'greet({"name":"Alice"})')
        resp = await client.call_tool('greet', {})
        _show(resp, 'greet({})')
        print()

        # 5. 测试 add 工具
        print('=== 5. tools/call add ===')
        resp = await client.call_tool('add', {'a': 3, 'b': 7})
        _show(resp, 'add({"a":3,"b":7})')
        resp = await client.call_tool('add', {'a': -5.2, 'b': 3.8})
        _show(resp, 'add({"a":-5.2,"b":3.8})')
        print()

        # 6. 错误 — 缺少必填参数
        print('=== 6. 错误 — 缺少必填参数 ===')
        resp = await client.call_tool('add', {'a': 1})
        _show(resp, 'add({"a":1})')
        print()

        # 7. 错误 — 未知工具
        print('=== 7. 错误 — 未知工具 ===')
        resp = await client.call_tool('nonexistent')
        _show(resp, 'nonexistent()')
        print()

        print('全部测试完成 [OK]')


def _show(resp: dict, label: str):
    if 'result' in resp:
        print(f'   {label} → {resp["result"]["content"][0]["text"]}')
    else:
        print(f'   {label} → [{resp["error"]["code"]}] {resp["error"]["message"]}')


if __name__ == '__main__':
    asyncio.run(main())
