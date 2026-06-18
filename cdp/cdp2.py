import asyncio
import json
import urllib.request
from urllib import parse

import websockets


class Driver:
    def __init__(self, ws):
        self._ws = ws

    async def open_tab(self, url: str) -> str:
        print(f"Opening tab: {url}")
        print(self._ws)
        if url:
            result = await self._ws.send('Target.createTarget', {'url': url})
        else:
            result = await self._ws.send('Target.createTarget', {'url': 'about:blank'})

        return result['targetId']


class Page:
    def __init__(self, ws, key):
        self._ws = ws
        self._id = key

    @property
    def id(self):
        return self._id


class CDPClient:
    def __init__(self, host: str = '127.0.0.1', port: int = 9222):
        self._host = host
        self._port = port
        self._driver: Driver = None
        self._pages = dict()

    def _fetch_browser_ws_url(self) -> str:
        resp = urllib.request.urlopen(f'http://{self._host}:{self._port}/json/version', timeout=5)
        return json.loads(resp.read())['webSocketDebuggerUrl']

    async def connect(self) -> None:
        # urllib 是同步阻塞的，扔到线程池避免卡住事件循环。目前没有内置异步 HTTP 库。
        ws_url = await asyncio.to_thread(self._fetch_browser_ws_url)
        ws = await websockets.connect(ws_url, max_size=2 ** 24)
        self._driver = Driver(ws)

    async def open_page(self, url: str = '') -> Page:
        if url != '':
            _r = parse.urlparse(url)
            key = f"{_r.scheme}://{_r.netloc}/{_r.path.strip('/')}"
        else:
            key = ''

        page = self._pages.get(key)
        if page is not None:
            return page
        print(url)
        target_id = await self._driver.open_tab(url)
        ws_url = f'ws://{self._host}:{self._port}/devtools/page/{target_id}'
        ws = await websockets.connect(ws_url, max_size=2 ** 24)

        page = Page(ws, key)
        self._pages[key] = page
        return page

    async def last_page(self) -> Page:
        ...


if __name__ == '__main__':
    async def main():
        url = 'https://www.bilibili.com/video/BV1ZkVg6hEeG/?spm_id_from=333.1007.tianma.1-2-2.click&vd_source=544102bc44b42747fd532b892c2f591e'
        client = CDPClient()
        await client.connect()
        page = await client.open_page(url)
        print(await page.id)


    asyncio.run(main())
