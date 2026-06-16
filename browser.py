import subprocess
import sys
import asyncio

import nodriver as uc

CDP_PORT = 9222


def ab_snapshot(interactive: bool = True) -> str:
    args = ['agent-browser', '--cdp', str(CDP_PORT), 'snapshot']
    if interactive:
        args.append('-i')
    if sys.platform == 'win32':
        args = ['pwsh', '-Command'] + args
    r = subprocess.run(args, capture_output=True, text=True, timeout=30, encoding='utf-8')
    return r.stdout.strip()


async def main():
    chrome_path = '/usr/bin/false' if sys.platform == 'linux' else None
    b = await uc.Browser.create(host='127.0.0.1', port=CDP_PORT,
                                browser_executable_path=chrome_path)

    for i in range(1):
        print(f'=== round {i+1} ===')
        tab = await b.get('https://www.zhipin.com/web/geek/jobs')
        await asyncio.sleep(5)
        title = await tab.evaluate('document.title')
        print(f'  title: {title}')
        print(f'  body:  {len(await tab.get_content())} chars')

        print()

    print('done - check Chrome tabs manually')


if __name__ == '__main__':
    asyncio.run(main())
