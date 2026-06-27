import asyncio
import json
import os
import random
import re

from .connection import CDPConnection

_INTERACTIVE_ROLES = frozenset({
    'link', 'button', 'textbox', 'combobox', 'checkbox',
    'listbox', 'menuitem', 'tab', 'switch', 'searchbox',
    'spinbutton', 'radio', 'menuitemcheckbox', 'menuitemradio',
    'option', 'slider', 'toggle', 'listitem',
})

_CONTENT_ROLES = frozenset({
    'heading', 'article', 'main', 'navigation', 'region',
    'listitem', 'cell', 'gridcell', 'columnheader', 'rowheader',
})

_INVISIBLE_CHARS = frozenset('\ufeff\u200b\u200c\u200d\u2060\u00a0')


def _resolve_js_code(action, **kwargs):
    path = os.path.join(os.path.dirname(__file__), 'js_code_template', f"{action}.md")
    with open(path, "r", encoding="utf-8") as f:
        txt = f.read()
    arr = re.findall(r'```(js)?([\w\W]+)```', txt)
    txt = re.sub(r'\s+', ' ', arr[0][1]).strip()
    for k, v in kwargs.items():
        txt = txt.replace(f"___{k}___", json.dumps(v, ensure_ascii=False))
    return txt


class Page:
    """页面层连接：操作单个 tab"""

    def __init__(self, conn: CDPConnection, target_id: str):
        self._conn = conn
        self._target_id = target_id
        self._refs: dict[str, tuple[int, str]] = {}

    @property
    def target_id(self) -> str:
        return self._target_id

    async def send(self, method: str, params: dict | None = None) -> dict:
        """透传底层 CDP 命令"""
        return await self._conn.send(method, params)

    async def close(self):
        await self._conn.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def navigate(self, url: str) -> dict:
        return await self._conn.send('Page.navigate', {'url': url})

    async def go_back(self):
        await self.evaluate('window.history.back()')

    @staticmethod
    def _find_child_name(nid: str, node_map: dict, visited: set | None = None) -> str:
        """递归查找子孙节点中第一个非忽略元素的名称，穿透忽略节点。"""
        if visited is None:
            visited = set()
        if nid in visited:
            return ''
        visited.add(nid)
        child = node_map.get(nid)
        if not child:
            return ''
        if not child.get('ignored'):
            name = (child.get('name') or {}).get('value', '') if isinstance(child.get('name'), dict) else ''
            if name:
                return name
        for cid in child.get('childIds', []):
            result = Page._find_child_name(cid, node_map, visited)
            if result:
                return result
        return ''

    @staticmethod
    def _collect_descendant_text(node: dict, node_map: dict, visited: set | None = None, seen: set | None = None) -> str:
        """递归收集节点子树中所有 StaticText/InlineTextBox 叶子文本，去重后用空格拼接。"""
        if visited is None:
            visited = set()
        if seen is None:
            seen = set()
        nid = node.get('nodeId', '')
        if nid in visited:
            return ''
        visited.add(nid)
        role_val = node.get('role', {})
        role = role_val.get('value', '').lower() if isinstance(role_val, dict) else ''
        parts: list[str] = []
        if role in ('statictext', 'inlinetextbox') and not node.get('ignored'):
            name = (node.get('name') or {}).get('value', '') if isinstance(node.get('name'), dict) else ''
            if name and name not in seen:
                seen.add(name)
                parts.append(name)
        for cid in node.get('childIds', []):
            child = node_map.get(cid)
            if child:
                text = Page._collect_descendant_text(child, node_map, visited, seen)
                if text:
                    parts.append(text)
        return ' '.join(parts)

    @staticmethod
    def _collect_descendant_backends(node: dict, node_map: dict, result: set) -> None:
        """收集节点子树中所有子孙的 backendDOMNodeId。"""
        for cid in node.get('childIds', []):
            child = node_map.get(cid)
            if child:
                cb = child.get('backendDOMNodeId')
                if cb:
                    result.add(cb)
                Page._collect_descendant_backends(child, node_map, result)

    async def evaluate(self, js_code: str):
        result = await self._conn.send('Runtime.evaluate', {
            'expression': js_code,
            'returnByValue': True,
        })
        exc = result.get('exceptionDetails')
        if exc:
            raise RuntimeError(
                str(exc.get('exception', {}).get('description', exc.get('text', '')))
            )
        return result.get('result', {}).get('value')

    async def title(self) -> str:
        return (await self.evaluate('document.title')) or ''

    async def url(self) -> str:
        return (await self.evaluate('document.URL')) or ''

    async def resolve_object_id(self, ref: str) -> str:
        if ref not in self._refs:
            raise KeyError(f'Unknown ref {ref}')
        backend_id, obj_id = self._refs[ref]
        if obj_id:
            return obj_id
        result = await self._conn.send('DOM.resolveNode', {'backendNodeId': backend_id})
        obj_id = result['object']['objectId']
        self._refs[ref] = (backend_id, obj_id)
        return obj_id

    async def extract_ax_tree(self) -> dict:
        await self._conn.send('Accessibility.enable')
        nodes = await self._conn.send('Accessibility.getFullAXTree')
        return nodes

    async def snapshot(self) -> str:
        """返回所有非忽略元素的平铺列表，与 get_content 的 ref 范围一致。

        格式 `@eN [role] <tag> "name"`，一行一个元素。
        包含 _INTERACTIVE_ROLES、_CONTENT_ROLES 及任何有名称的元素。
        listitem 会收集所有子孙文本拼接为名称，并屏蔽子元素输出。"""
        self._refs.clear()
        nodes = await self.extract_ax_tree()
        ax_nodes = nodes.get('nodes', [])
        node_map = {n['nodeId']: n for n in ax_nodes}
        covered_backends: set[int] = set()
        lines: list[str] = []
        ref_idx = 0

        for node in ax_nodes:
            role_val = node.get('role', {})
            role = role_val.get('value', '').lower() if isinstance(role_val, dict) else ''
            if not role or role in ('statictext', 'inlinetextbox', 'linebreak'):
                continue
            backend_id = node.get('backendDOMNodeId')
            if node.get('ignored') or not backend_id:
                continue
            if backend_id in covered_backends:
                continue

            show_role = role in (_INTERACTIVE_ROLES | _CONTENT_ROLES)

            name = (node.get('name') or {}).get('value', '') \
                if isinstance(node.get('name'), dict) else ''
            if not name:
                name = (node.get('value') or {}).get('value', '') \
                    if isinstance(node.get('value'), dict) else ''

            # listitem: 收集所有子孙文本，屏蔽子元素
            if role == 'listitem':
                desc_text = self._collect_descendant_text(node, node_map)
                if desc_text:
                    name = name + ' | ' + desc_text if name else desc_text
                self._collect_descendant_backends(node, node_map, covered_backends)
            elif not name:
                for cid in node.get('childIds', []):
                    child_name = self._find_child_name(cid, node_map)
                    if child_name:
                        name = child_name
                        break

            if not show_role and not name:
                continue

            ref_idx += 1
            ref = f'@e{ref_idx}'
            self._refs[ref] = (backend_id, '')

            props = {}
            for p in node.get('properties') or []:
                v = p.get('value', {})
                props[p.get('name', '')] = v.get('value', '') if isinstance(v, dict) else ''

            line = f'{ref} [{role}]'
            tag = props.get('htmlTag', '').lower()
            if tag:
                line += f' <{tag}>'
            if name:
                line += f' "{str(name)}"'
            url_prop = props.get('url', '')
            if url_prop and not url_prop.startswith('javascript:'):
                line += f' → {url_prop}'
            placeholder = props.get('placeholder', '')
            if placeholder:
                line += f' placeholder="{str(placeholder)}"'
            if props.get('checked'):
                line += ' (checked)'
            lines.append(line)

        return '\n'.join(lines) if lines else '(no interactive elements)'

    async def get_html(self) -> str:
        """返回页面完整的 HTML 源代码"""
        return (await self.evaluate('document.documentElement.outerHTML')) or ""

    async def screenshot(self, ref: str | None = None) -> str:
        """截图并返回 base64 编码的图片数据。ref: 对指定元素截图，不传则全页截图"""
        if ref is not None:
            backend_id = self._refs[ref][0]
            box = await self._conn.send('DOM.getBoxModel', {'backendNodeId': backend_id})
            model = box.get('model', {})
            content = model.get('content') or model.get('border') or model.get('padding') or model.get('margin')
            if not content:
                return ''
            x1, y1 = content[0], content[1]
            x2, y2 = content[4], content[5]
            clip = {'x': x1, 'y': y1, 'width': max(1, x2 - x1), 'height': max(1, y2 - y1), 'scale': 1}
            resp = await self._conn.send('Page.captureScreenshot', {
                'format': 'png',
                'clip': clip,
                'captureBeyondViewport': True,
            })
        else:
            resp = await self._conn.send('Page.captureScreenshot', {
                'format': 'png',
                'captureBeyondViewport': True,
            })
        return resp.get('data', '')

    async def get_text(self) -> str:
        """返回页面的结构化 Markdown 文本，基于 DOM 转 MD 转换"""
        js_code = await asyncio.to_thread(_resolve_js_code, 'get_text')
        return (await self.evaluate(js_code)) or ''

    async def get_content(self) -> str:
        """返回页面的结构化内容视图，基于无障碍树遍历，包含标题、文本、链接等"""
        self._refs.clear()
        nodes = await self.extract_ax_tree()
        ax_nodes = nodes.get('nodes', [])

        node_map: dict[str, dict] = {}
        child_map: dict[str, list[str]] = {}
        parent_map: dict[str, str] = {}
        for node in ax_nodes:
            nid = node.get('nodeId', '')
            node_map[nid] = node
            for cid in node.get('childIds', []):
                child_map.setdefault(nid, []).append(cid)
                parent_map[cid] = nid

        all_children: set[str] = set()
        for cids in child_map.values():
            all_children.update(cids)
        roots = [nid for nid in node_map if nid not in all_children]

        lines: list[str] = []
        ref_counter = [0]

        def _extract(val):
            if not val:
                return ''
            v = val.get('value', '')
            if isinstance(v, str):
                return v
            if v is not None:
                return str(v)
            return ''

        def _clean(s):
            return ''.join(c for c in s if c not in _INVISIBLE_CHARS).strip()

        def _render(nid: str, indent: int):
            node = node_map.get(nid)
            if not node:
                return

            role = _extract(node.get('role')).lower()
            children = child_map.get(nid, [])
            backend_id = node.get('backendDOMNodeId')
            ignored = node.get('ignored', False)

            if role in ('inlinetextbox', 'linebreak'):
                return

            if role == 'statictext':
                text = _clean(_extract(node.get('name')))
                if not text:
                    return
                pid = parent_map.get(nid, '')
                if pid and pid in node_map:
                    pname = _clean(_extract(node_map[pid].get('name')))
                    prole = _extract(node_map[pid].get('role')).lower()
                    if text == pname and prole not in ('generic', 'group', 'none', 'presentation'):
                        return
                prefix = '  ' * indent
                lines.append(f'{prefix}- text "{text[:120]}"')
                return

            if ignored or role in ('rootwebarea', 'webarea'):
                for cid in children:
                    _render(cid, indent)
                return

            if role in ('generic', 'group', 'none', 'presentation'):
                if not backend_id or len(children) <= 1:
                    for cid in children:
                        _render(cid, indent)
                    return

            name = _clean(_extract(node.get('name')))
            val = _clean(_extract(node.get('value')))
            display = name or val

            show_role = role in (_INTERACTIVE_ROLES | _CONTENT_ROLES)
            if not display and not show_role:
                for cid in children:
                    _render(cid, indent)
                return

            prefix = '  ' * indent
            line = f'{prefix}- {role}'
            if display:
                line += f' "{display[:120]}"'

            if backend_id and (show_role or display):
                ref_counter[0] += 1
                ref = f'@e{ref_counter[0]}'
                self._refs[ref] = (backend_id, '')
                line += f' [ref={ref}]'

            props: dict[str, str] = {}
            for p in node.get('properties') or []:
                pv = p.get('value', {})
                props[p.get('name', '')] = pv.get('value', '') if isinstance(pv, dict) else ''

            tag = props.get('htmlTag', '').lower()
            if tag:
                line += f' <{tag}>'

            url_prop = props.get('url', '')
            if url_prop and not url_prop.startswith('javascript:'):
                line += f' → {url_prop[:80]}'

            if role == 'heading':
                lv = props.get('level', '')
                if lv:
                    line += f' lv{lv}'

            if props.get('checked'):
                line += ' (checked)'
            if props.get('disabled'):
                line += ' (disabled)'
            if props.get('required'):
                line += ' (required)'
            if props.get('expanded') == 'false':
                line += ' (collapsed)'

            if val and val != name:
                line += f' value="{val[:60]}"'

            lines.append(line)

            for cid in children:
                _render(cid, indent + 1)

        for root in roots:
            _render(root, 0)

        return '\n'.join(lines) if lines else '(empty page)'

    async def click(self, ref: str):
        obj_id = await self.resolve_object_id(ref)
        js_code = await asyncio.to_thread(_resolve_js_code, 'click')
        params = {
            'objectId': obj_id,
            'functionDeclaration': js_code,
        }
        await self._conn.send('Runtime.callFunctionOn', params)

    async def scroll(self, ref: str | None = None, distance: int | None = None):
        """模拟真人滚轮滚动。ref: 滚到元素中心; distance: 滚动指定px; 都不传: 向下翻一屏"""
        if ref is not None:
            obj_id = await self.resolve_object_id(ref)
            js_code = await asyncio.to_thread(_resolve_js_code, 'scroll')
            result = await self._conn.send('Runtime.callFunctionOn', {
                'objectId': obj_id,
                'functionDeclaration': js_code,
                'returnByValue': True,
            })
            pos = result.get('result', {}).get('value', {})
            center_x = pos.get('x', 0)
            target_y = pos.get('y', 0)

            vp = await self.evaluate('({w: innerWidth, h: innerHeight})')
            vp_h = vp.get('h', 800)
            center_y = vp_h / 2
            total_dy = target_y - center_y
            if abs(total_dy) < 10:
                return
        else:
            vp = await self.evaluate('({w: innerWidth, h: innerHeight})')
            vp_w = vp.get('w', 1200)
            vp_h = vp.get('h', 800)
            center_x = vp_w / 2
            center_y = vp_h / 2
            if distance is not None:
                if distance == 0:
                    return
                total_dy = distance
            else:
                total_dy = random.randint(int(vp_h * 0.6), int(vp_h * 0.9))

        sign = 1 if total_dy > 0 else -1
        target = abs(total_dy)
        accumulated = 0.0

        while accumulated < target:
            remaining = max(target - accumulated, 1)
            base_step = random.randint(30, 80)
            step = min(base_step, remaining * 1.05)
            dy = sign * step * random.uniform(0.92, 1.08)

            await self._conn.send('Input.dispatchMouseEvent', {
                'type': 'mouseWheel',
                'x': center_x,
                'y': center_y,
                'deltaX': 0,
                'deltaY': round(dy, 1),
                'modifiers': 0,
                'button': 'none',
                'buttons': 0,
                'pointerType': 'mouse',
            })
            accumulated += abs(dy)

            progress = accumulated / target
            if progress < 0.15 or progress > 0.85:
                delay = random.uniform(0.025, 0.06)
            else:
                delay = random.uniform(0.01, 0.03)
            await asyncio.sleep(delay)

    async def fill(self, ref: str, text: str):
        obj_id = await self.resolve_object_id(ref)
        js_code = await asyncio.to_thread(_resolve_js_code, 'fill', value=text)
        params = {
            'objectId': obj_id,
            'functionDeclaration': js_code,
        }
        await self._conn.send('Runtime.callFunctionOn', params)


if __name__ == '__main__':
    async def main():
        js_code = await asyncio.to_thread(_resolve_js_code, 'fill', value=333333)
        print(js_code)


    asyncio.run(main())
