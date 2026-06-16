"""测试 Runtime.enable() 是否触发 zhipin 风控"""
import asyncio
from cdp import CDPClient

CDP_HOST = '127.0.0.1'
CDP_PORT = 9222


async def main():
    # 创建页面
    browser = CDPClient(CDP_HOST, CDP_PORT)
    await browser.connect()
    tid = (await browser.send('Target.createTarget', {'url': 'about:blank'}))['targetId']
    await browser.close()

    page = CDPClient(CDP_HOST, CDP_PORT)
    await page.connect(target_id=tid)

    # 导航到 zhipin
    await page.send('Page.navigate', {'url': 'https://www.zhipin.com/web/geek/jobs'})
    await asyncio.sleep(4)

    # 确认已加载
    r = await page.send('Runtime.evaluate',
                        {'expression': 'document.title', 'returnByValue': True})
    title = (r.get('result') or {}).get('value')
    print(f'页面已加载: title={title!r}')

    # 触发
    print('>>> 调用 Runtime.enable() ...')
    await page.send('Runtime.enable')

    for i in range(10):
        await asyncio.sleep(1)
        r = await page.send('Runtime.evaluate',
                            {'expression': 'document.URL', 'returnByValue': True})
        url = (r.get('result') or {}).get('value', '')
        if url == 'about:blank':
            print(f'  t={i + 1}s → BLOCKED! 页面被重定向到 about:blank')
            print()
            print('结论: Runtime.enable() 触发 zhipin 风控')
            return
        print(f'  t={i + 1}s → 正常 url={url[:60]}')

    print('10 秒内未触发 (可能间歇性)')

    await page.close()


if __name__ == '__main__':
    asyncio.run(main())
