import asyncio
import json
import logging
import websockets

_logger = logging.getLogger("cdp_driver")


class CDPConnection:
    """单条 WebSocket 的 CDP 消息协议层：序列化、路由、响应匹配"""

    def __init__(self):
        self._ws = None
        self._id = 0
        self._futures: dict[int, asyncio.Future] = {}
        self._event_callbacks: list = []

    async def connect(self, ws_url: str) -> None:
        if self._ws:
            await self.close()
            self._id = 0
            self._futures.clear()
        self._ws = await websockets.connect(ws_url, max_size=2 ** 24)
        asyncio.create_task(self._read_loop())

    def on_event(self, callback):
        """注册 CDP 事件回调 callback(method: str, params: dict)"""
        self._event_callbacks.append(callback)

    async def send(self, method: str, params: dict | None = None) -> dict:
        if self._ws is None:
            raise RuntimeError('CDP connection not established')
        self._id += 1
        msg: dict = {'id': self._id, 'method': method}
        if params:
            msg['params'] = params
        future = asyncio.get_running_loop().create_future()
        self._futures[self._id] = future
        try:
            await self._ws.send(json.dumps(msg))
            resp = await asyncio.wait_for(future, timeout=30)
        finally:
            self._futures.pop(self._id, None)
            future.cancel()
        err = resp.get('error')
        if err:
            raise RuntimeError(err.get('message', str(err)))
        return resp.get('result', {})

    async def _read_loop(self):
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                rid = msg.get('id')
                if rid is not None and rid in self._futures:
                    self._futures.pop(rid).set_result(msg)
                elif msg.get('method') and self._event_callbacks:
                    for cb in self._event_callbacks:
                        try:
                            result = cb(msg['method'], msg.get('params', {}))
                            if asyncio.iscoroutine(result):
                                asyncio.create_task(result)
                        except Exception:
                            _logger.debug("CDP 事件回调异常", exc_info=True)
        except websockets.ConnectionClosed:
            _logger.debug("CDP WebSocket 连接关闭")
        finally:
            for f in self._futures.values():
                if not f.done():
                    f.set_exception(RuntimeError('CDP connection closed'))
            self._futures.clear()

    async def close(self):
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
