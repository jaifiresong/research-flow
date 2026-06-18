import asyncio
import json
import urllib.request

import websockets


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
            self._ws = None
            self._id = 0
            self._futures.clear()
        self._ws = await websockets.connect(ws_url, max_size=2 ** 24)
        asyncio.create_task(self._read_loop())

    def on_event(self, callback):
        """注册 CDP 事件回调 callback(method: str, params: dict)"""
        self._event_callbacks.append(callback)

    async def send(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        msg: dict = {'id': self._id, 'method': method}
        if params:
            msg['params'] = params
        future = asyncio.get_event_loop().create_future()
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
                        cb(msg['method'], msg.get('params', {}))
        except websockets.ConnectionClosed:
            pass
        finally:
            for f in self._futures.values():
                if not f.done():
                    f.set_exception(RuntimeError('CDP connection closed'))
            self._futures.clear()

    async def close(self):
        if self._ws:
            await self._ws.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()


class Driver:
    """浏览器层连接：管理 targets"""

    def __init__(self, conn: CDPConnection):
        self._conn = conn

    async def open_tab(self, url: str | None = None) -> str:
        if not url:
            url = 'about:blank'
        result = await self._conn.send('Target.createTarget', {'url': url})
        return result['targetId']

    async def close(self):
        await self._conn.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()


class Page:
    """页面层连接：操作单个 tab"""

    def __init__(self, conn: CDPConnection, target_id: str):
        self._conn = conn
        self._target_id = target_id

    @property
    def target_id(self) -> str:
        return self._target_id

    async def navigate(self, url: str) -> dict:
        return await self._conn.send('Page.navigate', {'url': url})

    async def evaluate(self, js: str):
        result = await self._conn.send('Runtime.evaluate', {
            'expression': js,
            'returnByValue': True,
        })
        exc = result.get('exceptionDetails')
        if exc:
            raise RuntimeError(
                str(exc.get('exception', {}).get('description', exc.get('text', '')))
            )
        return result.get('result', {}).get('value')

    async def send(self, method: str, params: dict | None = None) -> dict:
        """透传底层 CDP 命令"""
        return await self._conn.send(method, params)

    async def close(self):
        await self._conn.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()


class CDPClient:
    """会话入口：创建 Driver、管理 Page 池"""

    def __init__(self, host: str = '127.0.0.1', port: int = 9222):
        self._host = host
        self._port = port
        self._driver: Driver | None = None
        self._pages: dict[str, Page] = {}

    def _fetch_browser_ws_url(self) -> str:
        resp = urllib.request.urlopen(
            f'http://{self._host}:{self._port}/json/version', timeout=5)
        return json.loads(resp.read())['webSocketDebuggerUrl']

    async def connect(self) -> None:
        ws_url = await asyncio.to_thread(self._fetch_browser_ws_url)
        conn = CDPConnection()
        await conn.connect(ws_url)
        self._driver = Driver(conn)

    async def open_page(self, url: str | None = None) -> Page:
        target_id = await self._driver.open_tab(url)
        ws_url = f'ws://{self._host}:{self._port}/devtools/page/{target_id}'
        conn = CDPConnection()
        await conn.connect(ws_url)
        page = Page(conn, target_id)
        self._pages[target_id] = page
        return page

    async def close(self) -> None:
        for page in list(self._pages.values()):
            await page.close()
        self._pages.clear()
        if self._driver:
            await self._driver.close()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.close()


if __name__ == '__main__':
    async def main():
        async with CDPClient() as client:
            page = await client.open_page()
            print('target_id:', page.target_id)

            await asyncio.sleep(3)

            nav = await page.navigate('https://example.com/')
            print('navigate result:', nav)

            title = await page.evaluate('document.title')
            print('title:', title)


    asyncio.run(main())
