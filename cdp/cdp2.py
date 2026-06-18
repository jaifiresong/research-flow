import asyncio
import json
import urllib.request

import websockets

"""
API 反爬安全评估
- Runtime.evaluate --- API 层面不留痕迹，但要注意注入的 JS 代码本身别太可疑

以后加新功能时有风险的命令
- Accessibility.enable — 会修改 DOM 结构，JS 可检测（常见反爬检查点）
- Runtime.enable / Page.enable — 启用 domain 监听后某些行为会变
- DOM.enable — 开启 DOM 代理追踪
"""

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
        if self._ws is None:
            raise RuntimeError('CDP connection not established')
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
                        try:
                            result = cb(msg['method'], msg.get('params', {}))
                            if asyncio.iscoroutine(result):
                                asyncio.create_task(result)
                        except Exception:
                            pass
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

    async def enable_discovery(self) -> None:
        await self._conn.send('Target.setDiscoverTargets', {'discover': True})

    def on(self, method: str, callback):
        """按方法名注册 CDP 事件回调 callback(params: dict)"""
        def _wrap(event_method: str, params: dict):
            if event_method == method:
                return callback(params)
            return None

        self._conn.on_event(_wrap)

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
        self._new_page_callback = None

    def _fetch_browser_ws_url(self) -> str:
        resp = urllib.request.urlopen(
            f'http://{self._host}:{self._port}/json/version', timeout=5)
        return json.loads(resp.read())['webSocketDebuggerUrl']

    async def connect(self) -> None:
        if self._driver is not None:
            await self.close()
        ws_url = await asyncio.to_thread(self._fetch_browser_ws_url)
        conn = CDPConnection()
        await conn.connect(ws_url)
        self._driver = Driver(conn)
        await self._driver.enable_discovery()
        self._driver.on('Target.targetCreated', self._on_target_created)

    async def _on_target_created(self, params: dict) -> None:
        info = params.get('targetInfo', {})
        if info.get('type') != 'page':
            return
        target_id = info['targetId']
        if target_id in self._pages:
            return
        ws_url = f'ws://{self._host}:{self._port}/devtools/page/{target_id}'
        conn = CDPConnection()
        await conn.connect(ws_url)
        page = Page(conn, target_id)
        self._pages[target_id] = page
        cb = self._new_page_callback
        if cb:
            cb(page)

    def on_new_page(self, callback):
        """注册回调 callback(page: Page)，每当浏览器自动创建新 tab 时触发"""
        self._new_page_callback = callback

    async def open_page(self, url: str | None = None) -> Page:
        target_id = await self._driver.open_tab(url)
        existing = self._pages.get(target_id)
        if existing is not None:
            return existing
        self._pages[target_id] = None
        try:
            ws_url = f'ws://{self._host}:{self._port}/devtools/page/{target_id}'
            conn = CDPConnection()
            await conn.connect(ws_url)
            page = Page(conn, target_id)
            self._pages[target_id] = page
            return page
        except BaseException:
            self._pages.pop(target_id, None)
            raise

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
