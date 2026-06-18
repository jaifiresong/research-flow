"""Minimal browser automation via raw CDP — open, snapshot, click, fill."""
import asyncio
import json
from cdp_client import CDPClient

INTERACTIVE_ROLES = frozenset({
    'link', 'button', 'textbox', 'combobox', 'checkbox',
    'listbox', 'menuitem', 'tab', 'switch', 'searchbox',
    'spinbutton', 'radio', 'menuitemcheckbox', 'menuitemradio',
    'option', 'slider', 'toggle',
})


class Browser:
    def __init__(self, host: str = '127.0.0.1', port: int = 9222):
        self._host = host
        self._port = port
        self._cdp: CDPClient | None = None
        self._target_id: str = ''
        self._refs: dict[str, tuple[int, str]] = {}

    async def start(self):
        browser = CDPClient(self._host, self._port)
        await browser.connect()
        result = await browser.send('Target.createTarget', {'url': 'about:blank'})
        self._target_id = result['targetId']
        await browser.close()
        self._cdp = CDPClient(self._host, self._port)
        await self._cdp.connect(target_id=self._target_id)

    # ── navigation ──

    async def open(self, url: str, spa_wait: float = 0):
        nav = await self._cdp.send('Page.navigate', {'url': url})
        if nav.get('errorText'):
            raise RuntimeError(nav['errorText'])
        await self._wait_ready(spa_wait=spa_wait)

    async def _wait_ready(self, spa_wait: float = 1.0):
        # 不用 Runtime.evaluate polling，避免在页面加载期间 enable Runtime
        await asyncio.sleep(spa_wait)

    # ── snapshot ──

    async def snapshot(self) -> str:
        self._refs.clear()
        await self._cdp.send('Accessibility.enable')
        nodes = await self._cdp.send('Accessibility.getFullAXTree')
        ax_nodes = nodes.get('nodes', [])
        lines: list[str] = []
        ref_idx = 0

        for node in ax_nodes:
            role_val = node.get('role', {})
            role = role_val.get('value', '').lower() if isinstance(role_val, dict) else ''
            if not role or role not in INTERACTIVE_ROLES:
                continue
            backend_id = node.get('backendDOMNodeId')
            if node.get('ignored') or not backend_id:
                continue

            ref_idx += 1
            ref = f'@e{ref_idx}'
            self._refs[ref] = (backend_id, '')

            name = (node.get('name') or {}).get('value', '') \
                if isinstance(node.get('name'), dict) else ''
            if not name:
                name = (node.get('value') or {}).get('value', '') \
                    if isinstance(node.get('value'), dict) else ''

            props = {}
            for p in node.get('properties') or []:
                v = p.get('value', {})
                props[p.get('name', '')] = v.get('value', '') if isinstance(v, dict) else ''

            line = f'{ref} [{role}]'
            tag = props.get('htmlTag', '').lower()
            if tag:
                line += f' <{tag}>'
            if name:
                line += f' "{str(name)[:80]}"'
            url_prop = props.get('url', '')
            if url_prop and not url_prop.startswith('javascript:'):
                line += f' → {url_prop[:80]}'
            placeholder = props.get('placeholder', '')
            if placeholder:
                line += f' placeholder="{str(placeholder)[:40]}"'
            if props.get('checked'):
                line += ' (checked)'
            lines.append(line)

        return '\n'.join(lines) if lines else '(no interactive elements)'

    async def extract_ax_tree(self) -> dict:
        await self._cdp.send('Accessibility.enable')
        nodes = await self._cdp.send('Accessibility.getFullAXTree')
        return nodes

    # ── interaction ──

    async def click(self, ref: str):
        obj_id = await self._object_id(ref)
        await self._cdp.send('Runtime.callFunctionOn', {
            'functionDeclaration': (
                'function(){'
                'this.scrollIntoView({block:"center",behavior:"instant"});'
                'this.click();'
                '}'
            ),
            'objectId': obj_id,
        })
        await self._wait_ready()

    async def fill(self, ref: str, text: str):
        obj_id = await self._object_id(ref)
        escaped = json.dumps(text)
        await self._cdp.send('Runtime.callFunctionOn', {
            'functionDeclaration': (
                f'function(){{'
                f'this.focus();'
                f'this.value="";'
                f'if(this.tagName=="SELECT"){{'
                f'  for(let o of this.options)if(o.text.includes({escaped})){{o.selected=true;break}}'
                f'  this.dispatchEvent(new Event("change",{{bubbles:true}}));'
                f'}}else{{'
                f'  this.value={escaped};'
                f'  this.dispatchEvent(new Event("input",{{bubbles:true}}));'
                f'  this.dispatchEvent(new Event("change",{{bubbles:true}}));'
                f'}}'
            ),
            'objectId': obj_id,
        })

    async def type(self, ref: str, text: str):
        await self.fill(ref, text)

    async def _object_id(self, ref: str) -> str:
        if ref not in self._refs:
            raise KeyError(f'Unknown ref {ref}')
        backend_id, obj_id = self._refs[ref]
        if obj_id:
            return obj_id
        result = await self._cdp.send('DOM.resolveNode',
                                      {'backendNodeId': backend_id})
        obj_id = result['object']['objectId']
        self._refs[ref] = (backend_id, obj_id)
        return obj_id

    # ── scroll ──

    async def scroll(self, direction: str = 'down', amount: float = 1440,
                     ref: str | None = None):
        """按方向滚动页面或指定元素，循环直到达到 amount 或到达边界。

        循环在一次 JS 调用内完成，直接赋值 scrollTop/scrollLeft 同步生效，
        当场比较判断是否到边界（无进展）或达目标。
        """
        signs = {'up': -1, 'down': 1, 'left': -1, 'right': 1}
        if direction not in signs:
            raise ValueError(f'未知方向: {direction}')
        horiz = direction in ('left', 'right')
        sign = signs[direction]
        axis = 'scrollLeft' if horiz else 'scrollTop'
        step = max(int(amount / 12), 60)
        target = int(amount)
        el = 'this' if ref else 'document.scrollingElement'
        body = (
            f'const el={el},s=el.{axis};'
            f'for(let i=0;i<100;i++){{'
            f'const b=el.{axis};'
            f'el.{axis}+={sign}*{step};'
            f'if(el.{axis}===b||Math.abs(el.{axis}-s)>={target})break;'
            f'}}'
        )
        if ref:
            obj_id = await self._object_id(ref)
            await self._cdp.send('Runtime.callFunctionOn', {
                'functionDeclaration': f'function(){{{body}}}',
                'objectId': obj_id,
            })
        else:
            await self.evaluate(f'(()=>{{{body}}})()')

    async def scroll_to_bottom(self):
        """滚动页面到底部。"""
        await self.evaluate('window.scrollTo(0, document.body.scrollHeight)')

    async def scroll_into_view(self, ref: str):
        """将指定元素滚动到可视区域中央。

        Args:
            ref: 快照中的元素引用（例如 @e1）。
        """
        obj_id = await self._object_id(ref)
        await self._cdp.send('Runtime.callFunctionOn', {
            'functionDeclaration': (
                'function(){'
                'this.scrollIntoView({block:"center",inline:"center",behavior:"instant"});'
                '}'
            ),
            'objectId': obj_id,
        })

    # ── read ──

    async def evaluate(self, js: str):
        result = await self._cdp.send('Runtime.evaluate', {
            'expression': js,
            'returnByValue': True,
        })
        exc = result.get('exceptionDetails')
        if exc:
            raise RuntimeError(str(exc.get('exception', {}).get('description', exc.get('text', ''))))
        return result.get('result', {}).get('value')

    async def title(self) -> str:
        return (await self.evaluate('document.title')) or ''

    async def url(self) -> str:
        return (await self.evaluate('document.URL')) or ''

    async def close(self):
        if self._cdp:
            await self._cdp.close()


if __name__ == '__main__':
    async def main():
        b = Browser(port=9222)
        await b.start()

        print('=== open zhipin ===')
        await b.open('https://www.zhipin.com/web/geek/jobs', spa_wait=4)
        print('title:', await b.title())
        print('url:', await b.url())

        await asyncio.sleep(3)
        print('after 3s: title:', await b.title())
        print('after 3s: url:', await b.url())

        print()
        print('=== snapshot ===')
        snap = await b.snapshot()

        print(snap)

        await b.click('@e75')
        await b.close()


    asyncio.run(main())
