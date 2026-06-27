"""
API 反爬安全评估
- Runtime.evaluate --- API 层面不留痕迹，但要注意注入的 JS 代码本身别太可疑

以后加新功能时有风险的命令
- Accessibility.enable — 会修改 DOM 结构，JS 可检测（常见反爬检查点）
- Runtime.enable / Page.enable — 启用 domain 监听后某些行为会变
- DOM.enable — 开启 DOM 代理追踪
"""

import asyncio
import json
import urllib.request

from .connection import CDPConnection
from .page import Page


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

    async def send(self, method: str, params: dict | None = None) -> dict:
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
        self._active_page_id: str | None = None

    async def __aenter__(self):
        try:
            await self.connect()
        except BaseException:
            await self.close()
            raise
        return self

    async def __aexit__(self, *args):
        await self.close()

    def _fetch_browser_ws_url(self) -> str:
        resp = urllib.request.urlopen(
            f'http://{self._host}:{self._port}/json/version', timeout=5)
        return json.loads(resp.read())['webSocketDebuggerUrl']

    def _fetch_json_targets(self) -> list[dict]:
        """查询 HTTP /json 端点，按 tab 条顺序返回页面列表（第一个为激活 tab）"""
        resp = urllib.request.urlopen(
            f'http://{self._host}:{self._port}/json', timeout=5)
        return json.loads(resp.read())

    async def _attach_existing_pages(self) -> None:
        """接管浏览器中已打开的 page 类型 target

        同时查询 HTTP /json 端点获取 tab 顺序（Chrome 按 tab 条顺序返回，
        第一个即为激活的 tab），记录 _active_page_id。
        """
        if self._driver is None:
            return
        result = await self._driver.send('Target.getTargets')
        target_ids = {
            info['targetId'] for info in result.get('targetInfos', [])
            if info.get('type') == 'page'
        }

        # 通过 HTTP /json 获取激活的 tab（列表第一个）
        json_targets = await asyncio.to_thread(self._fetch_json_targets)

        for jt in json_targets:
            target_id = jt['id']
            if target_id not in target_ids or target_id in self._pages:
                continue
            ws_url = jt.get('webSocketDebuggerUrl', '')
            if not ws_url:
                ws_url = f'ws://{self._host}:{self._port}/devtools/page/{target_id}'
            conn = CDPConnection()
            await conn.connect(ws_url)
            page = Page(conn, target_id)
            self._pages[target_id] = page
            cb = self._new_page_callback
            if cb:
                result_cb = cb(page)
                if asyncio.iscoroutine(result_cb):
                    await result_cb

        # 记录激活的 tab（HTTP /json 返回列表的第一个 page）
        if self._active_page_id is None:
            for jt in json_targets:
                if jt.get('type') == 'page' and jt['id'] in self._pages:
                    self._active_page_id = jt['id']
                    break

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
            result = cb(page)
            if asyncio.iscoroutine(result):
                await result

    async def connect(self) -> None:
        if self._driver is not None:
            await self.close()
        ws_url = await asyncio.to_thread(self._fetch_browser_ws_url)
        conn = CDPConnection()
        await conn.connect(ws_url)
        self._driver = Driver(conn)
        await self._driver.enable_discovery()
        await self._attach_existing_pages()
        self._driver.on('Target.targetCreated', self._on_target_created)

    async def active_page(self) -> Page | None:
        """返回当前可见（激活）的 page，没有则返回 None

        检测策略：
        1. 优先返回 open_page 最近创建的 tab（Target.createTarget 会自动激活）
        2. 并行检测所有 page 的 document.visibilityState（可能因 CDP 连接副作用全返回 hidden）
        3. 兜底：返回第一个可响应的 page
        """
        # 策略 1：最近通过 open_page 创建的 tab（Chrome 自动激活）
        if self._active_page_id and self._active_page_id in self._pages:
            page = self._pages[self._active_page_id]
            if page is not None:
                return page

        async def _check(page: Page) -> tuple[Page, str] | None:
            try:
                state = await page.evaluate('document.visibilityState')
                return (page, state)
            except Exception:
                return None

        # 策略 2：并行检测 visibilityState
        valid_pages = [p for p in self._pages.values() if p is not None]
        results = await asyncio.gather(*(_check(p) for p in valid_pages))
        for r in results:
            if r and r[1] == 'visible':
                return r[0]

        # 策略 3：兜底，返回任意可响应的 page
        for r in results:
            if r:
                return r[0]

        return None

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
            self._active_page_id = target_id
            return page
        except BaseException:
            self._pages.pop(target_id, None)
            raise

    async def close(self) -> None:
        for page in list(self._pages.values()):
            if page is not None:
                await page.close()
        self._pages.clear()
        if self._driver:
            await self._driver.close()

    async def close_page(self, page: Page) -> None:
        """关闭指定标签页，并从 page 池中移除。"""
        target_id = page.target_id
        await page.close()
        self._pages.pop(target_id, None)
        await self._driver.send('Target.closeTarget', {'targetId': target_id})


if __name__ == '__main__':
    ...
