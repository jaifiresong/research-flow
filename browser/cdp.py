"""CDP client: raw WebSocket communication with Chrome DevTools Protocol."""
import asyncio
import json
import urllib.request

import websockets


class CDPClient:
    """Connect to Chrome's DevTools WebSocket (browser or page level)."""

    def __init__(self, host: str = '127.0.0.1', port: int = 9222):
        self._host = host
        self._port = port
        self._ws = None
        self._id = 0
        self._futures: dict[int, asyncio.Future] = {}

    async def connect(self, target_id: str | None = None):
        if target_id:
            ws_url = f'ws://{self._host}:{self._port}/devtools/page/{target_id}'
        else:
            ws_url = await asyncio.to_thread(self._fetch_browser_ws_url)
        self._ws = await websockets.connect(ws_url, max_size=2 ** 24)
        asyncio.create_task(self._read_loop())

    def _fetch_browser_ws_url(self) -> str:
        resp = urllib.request.urlopen(f'http://{self._host}:{self._port}/json/version', timeout=5)
        return json.loads(resp.read())['webSocketDebuggerUrl']

    async def _read_loop(self):
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                rid = msg.get('id')
                if rid is not None and rid in self._futures:
                    self._futures.pop(rid).set_result(msg)
        except websockets.ConnectionClosed:
            pass

    async def send(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        msg: dict = {'id': self._id, 'method': method}
        if params:
            msg['params'] = params
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._futures[self._id] = future
        await self._ws.send(json.dumps(msg))
        resp = await asyncio.wait_for(future, timeout=30)
        err = resp.get('error')
        if err:
            raise RuntimeError(err.get('message', str(err)))
        return resp.get('result', {})

    async def close(self):
        if self._ws:
            await self._ws.close()
