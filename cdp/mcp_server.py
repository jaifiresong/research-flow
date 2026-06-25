#!/usr/bin/env python3
"""MCP 原生底层工作原理示例 (stdio JSON-RPC)"""

import asyncio, inspect, json, sys, traceback

VERSION = '1.0.0'
PROTOCOL_VERSION = '2024-11-05'


def log(msg: str) -> None:
    print(f'[mcp] {msg}', file=sys.stderr, flush=True)


class MCPServer:
    """MCP 协议在 stdio 上的完整生命周期演示"""

    def __init__(self):
        self._tools: list[dict] = []
        self._handlers: dict[str, callable] = {}

    @staticmethod
    def _type_to_schema(typ) -> dict:
        mapping = {str: 'string', int: 'integer', float: 'number', bool: 'boolean', list: 'array', dict: 'object', type(None): 'null'}
        return {'type': mapping.get(typ, 'string')}

    def tool(self, name: str | None = None, description: str | None = None, input_schema: dict | None = None):
        """装饰器：注册工具到 MCP。name/description/input_schema 缺省时从函数自动提取。"""

        def decorator(func):
            n = name or func.__name__
            d = description or (func.__doc__ or '').strip() or ''
            sig = inspect.signature(func)
            props, required = {}, []
            for p_name, p in sig.parameters.items():
                if p_name in ('self', 'cls'):
                    continue
                if p.default is inspect.Parameter.empty:
                    required.append(p_name)
                type_schema = self._type_to_schema(p.annotation) if p.annotation is not inspect.Parameter.empty else {'type': 'string'}
                props[p_name] = type_schema
            schema = input_schema or {'type': 'object', 'properties': props, 'required': required}

            self._tools.append({'name': n, 'description': d, 'inputSchema': schema})
            self._handlers[n] = func
            return func

        return decorator

    async def run(self) -> None:
        while True:
            raw = await asyncio.to_thread(sys.stdin.buffer.readline)
            if not raw:
                break
            line = raw.decode('utf-8').strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                continue

            resp = await self._dispatch(req)
            if resp is not None:
                payload = json.dumps(resp, ensure_ascii=False).encode('utf-8')
                sys.stdout.buffer.write(payload + b'\n')
                sys.stdout.buffer.flush()

    async def _dispatch(self, req: dict) -> dict | None:
        method, req_id, params = req.get('method', ''), req.get('id'), req.get('params', {})
        log(f'-> {method}')

        try:
            if method == 'initialize':
                return {
                    'jsonrpc': '2.0', 'id': req_id,
                    'result': {
                        'protocolVersion': PROTOCOL_VERSION,
                        'capabilities': {'tools': {}},
                        'serverInfo': {'name': 'mcp_demo', 'version': VERSION},
                    },
                }

            if method == 'notifications/initialized':
                log('MCP 握手完成')
                return None

            if method == 'ping':
                return {'jsonrpc': '2.0', 'id': req_id, 'result': {}}

            if method == 'tools/list':
                return {'jsonrpc': '2.0', 'id': req_id, 'result': {'tools': self._tools}}

            if method == 'tools/call':
                tool_name = params.get('name', '')
                args = params.get('arguments', {})
                handler = self._handlers.get(tool_name)
                if not handler:
                    return {'jsonrpc': '2.0', 'id': req_id, 'error': {'code': -32601, 'message': f'未知工具: {tool_name}'}}

                try:
                    result = await handler(**args) if asyncio.iscoroutinefunction(handler) else handler(**args)
                except Exception as e:
                    log(f'工具执行失败: {traceback.format_exc()}')
                    return {'jsonrpc': '2.0', 'id': req_id, 'error': {'code': -32000, 'message': str(e)}}

                return {'jsonrpc': '2.0', 'id': req_id, 'result': {'content': [{'type': 'text', 'text': str(result)}]}}

            return {'jsonrpc': '2.0', 'id': req_id, 'error': {'code': -32601, 'message': f'未知方法: {method}'}}

        except Exception as e:
            log(traceback.format_exc())
            return {'jsonrpc': '2.0', 'id': req_id, 'error': {'code': -32603, 'message': str(e)}}


async def main():
    server = MCPServer()

    @server.tool()
    async def greet(name: str = 'World') -> str:
        """向用户发送问候"""
        return f'Hello, {name}! from MCP'

    @server.tool()
    def add(a: float, b: float) -> float:
        """两数相加"""
        return a + b

    try:
        await server.run()
    except asyncio.CancelledError:
        pass
    except Exception:
        log(traceback.format_exc())


if __name__ == '__main__':
    asyncio.run(main())
