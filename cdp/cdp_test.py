import asyncio

from cdp.cdp_client import CDPClient


class Browser:
    def __init__(self):
        self.client = CDPClient()

    async def connect(self):
        await self.client.connect()

    async def open(self):
        """打开一个空白页"""
        # result = await self.client.send('Target.createTarget', {'url': 'about:blank'})
        # result = await self.client.send('Target.createTarget', {'url': 'https://example.com'})
        # result = await self.client.send('Page.navigate', {'url': 'https://example.com'})
        # print(result)
        """打开一个空白页"""
        # 第一步：在浏览器级别创建新标签页
        result = await self.client.send('Target.createTarget', {'url': 'about:blank'})
        target_id = result['targetId']
        print(f"Created target: {target_id}")

        # 第二步：关闭当前浏览器级别的连接
        await self.client.close()

        # 第三步：连接到新创建的页面级别 WebSocket
        await self.client.connect(target_id=target_id)

        # 第四步：现在可以在页面级别执行 Page.navigate 了
        result = await self.client.send('Page.navigate', {'url': 'https://example.com'})
        print(result)


async def main():
    browser = Browser()
    await browser.connect()
    await browser.open()


if __name__ == '__main__':
    asyncio.run(main())
