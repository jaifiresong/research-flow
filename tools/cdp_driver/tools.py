import inspect
import logging
import re
import types
from typing import Any

from .core.client import CDPClient
from .core.page import Page

_logger = logging.getLogger("cdp_driver")


def _annotation_to_json_type(ann: Any) -> str:
    """将 Python 类型注解转为 JSON Schema 类型字符串"""
    if ann in (inspect.Parameter.empty, str):
        return 'string'
    if ann is int:
        return 'integer'
    if ann is float:
        return 'number'
    if ann is bool:
        return 'boolean'
    if ann is list:
        return 'array'
    if ann is dict:
        return 'object'
    origin = getattr(ann, '__origin__', None)
    if origin is types.UnionType:
        args = [a for a in getattr(ann, '__args__', ()) if a is not type(None)]
        if len(args) == 1:
            return _annotation_to_json_type(args[0])
    return 'string'


def tool(func):
    """装饰器：标记方法为 agent 工具，从签名和 docstring 自动生成 JSON Schema。

    docstring 格式要求：
    - 第一行 = 工具描述
    - Args: 段落 = 参数说明（每行 "param: desc"）
    - 类型提示 → JSON Schema 类型
    - 默认值 → 可选参数
    """
    sig = inspect.signature(func)
    doc = inspect.getdoc(func) or ''

    lines = doc.split('\n')
    description = lines[0].strip() if lines else ''

    param_descs: dict[str, str] = {}
    in_args = False
    for line in lines[1:]:
        stripped = line.strip()
        if re.match(r'^[Aa]rgs?:?\s*$', stripped):
            in_args = True
            continue
        if in_args:
            if not stripped:
                continue
            if re.match(r'^(Returns?:|Raises?:|Note)', stripped):
                break
            m = re.match(r'^(\w+)\s*:\s*(.*)', stripped)
            if m:
                param_descs[m.group(1)] = m.group(2)

    properties: dict[str, dict] = {}
    required: list[str] = []
    for name, param in sig.parameters.items():
        if name == 'self':
            continue
        prop: dict[str, Any] = {'type': _annotation_to_json_type(param.annotation)}
        if name in param_descs:
            prop['description'] = param_descs[name]
        if param.default is not inspect.Parameter.empty:
            prop['default'] = param.default
        else:
            required.append(name)
        properties[name] = prop

    input_schema: dict[str, Any] = {'type': 'object', 'properties': properties}
    if required:
        input_schema['required'] = required

    func._tool_schema = {
        'description': description,
        'inputSchema': input_schema,
    }
    func._is_tool = True

    return func


class BrowserTools:
    """浏览器自动化工具集，供 AI Agent 调用。

    Usage:
        # 直接使用
        bt = BrowserTools()
        await bt.connect()
        await bt.open_page("https://example.com")
        text = await bt.get_text()
        img = await bt.screenshot()
        await bt.close()

        # LangChain 集成
        from cdp_driver.tools import BrowserTools
        bt = BrowserTools()
        await bt.connect()
        agent = create_react_agent(llm, bt.as_langchain_tools())

        # 通用 agent 集成
        for schema in bt.schemas:
            register_tool(schema, lambda **kw: bt.call(name=schema['name'], **kw))

        # Context manager
        async with BrowserTools() as bt:
            await bt.open_page("https://example.com")
    """

    def __init__(self):
        self._client: CDPClient | None = None
        self._page: Page | None = None

    def _require_page(self) -> Page:
        if self._page is None:
            raise RuntimeError('没有活跃页面，请先调用 open_page 或 active_page')
        return self._page

    # ── lifecycle ──

    @tool
    async def connect(self, host: str = '127.0.0.1', port: int = 9222) -> str:
        """连接到 Chrome 浏览器的 DevTools 端口。

        Args:
            host: Chrome DevTools 主机地址
            port: Chrome DevTools 端口号
        """
        _logger.info("connect: %s:%s", host, port)
        self._client = CDPClient(host, port)
        await self._client.connect()
        _logger.info("connect: 已连接到 %s:%s", host, port)
        return f'已连接到 {host}:{port}'

    @tool
    async def close(self) -> str:
        """关闭与 Chrome 浏览器的连接，释放所有资源。"""
        _logger.info("close: 正在关闭连接 (pages=%d)", len(self._client._pages) if self._client else 0)
        if self._client:
            await self._client.close()
            self._client = None
            self._page = None
        _logger.info("close: 已关闭")
        return '已关闭连接'

    @tool
    async def open_page(self, url: str | None = None) -> str:
        """打开新标签页并导航到指定 URL。

        Args:
            url: 目标 URL，留空则打开空白页
        """
        _logger.info("open_page: url=%s", url)
        if self._client is None:
            _logger.error("open_page: 未连接")
            raise RuntimeError('未连接，请先调用 connect')
        self._page = await self._client.open_page(url)
        page_url = await self._page.url()
        _logger.info("open_page: 已打开 %s", page_url)
        return f'已打开页面: {page_url}'

    @tool
    async def active_page(self) -> str:
        """切换到浏览器当前激活的标签页。"""
        _logger.info("active_page: 正在查找活跃页面")
        if self._client is None:
            _logger.error("active_page: 未连接")
            raise RuntimeError('未连接，请先调用 connect')
        self._page = await self._client.active_page()
        if self._page is None:
            _logger.warning("active_page: 未找到活跃页面")
            raise RuntimeError('未找到活跃页面')
        page_url = await self._page.url()
        _logger.info("active_page: 已切换到 %s", page_url)
        return f'已切换到: {page_url}'

    # ── navigation & info ──

    @tool
    async def navigate(self, url: str) -> str:
        """导航当前页面到指定 URL。

        Args:
            url: 目标网页地址
        """
        await self._require_page().navigate(url)
        return f'已导航到 {url}'

    @tool
    async def go_back(self) -> str:
        """返回上一页，等价于点击浏览器的后退按钮。"""
        await self._require_page().go_back()
        return '已返回上一页'

    @tool
    async def close_page(self) -> str:
        """关闭当前页面（标签页）。关闭后需用 open_page 或 active_page 切换到其他页面才能继续操作。"""
        if self._client is None or self._page is None:
            return '没有可关闭的页面'
        await self._client.close_page(self._page)
        self._page = None
        return '已关闭当前页面'

    @tool
    async def title(self) -> str:
        """获取当前页面的标题。"""
        return await self._require_page().title()

    @tool
    async def url(self) -> str:
        """获取当前页面的 URL。"""
        return await self._require_page().url()

    # ── evaluation ──

    @tool
    async def evaluate(self, js_code: str) -> str:
        """在当前页面执行 JavaScript 代码并返回结果。

        Args:
            js_code: 要执行的 JavaScript 代码
        """
        result = await self._require_page().evaluate(js_code)
        return str(result)

    # ── content extraction ──

    @tool
    async def snapshot(self) -> str:
        """获取页面元素的平铺列表，@eN 编号范围与 get_content 完全一致。

        返回格式 `@eN [role] <tag> "name"`，一行一个元素。
        包含所有交互元素、内容元素及有名称的元素，不含纯文本节点。
        适合快速扫描和精准操作，需要了解页面层级结构时请用 get_content。"""
        return await self._require_page().snapshot()

    @tool
    async def get_html(self) -> str:
        """返回当前页面的完整 HTML 源代码。"""
        return await self._require_page().get_html()

    @tool
    async def get_text(self) -> str:
        """返回当前页面的结构化 Markdown 文本，保留标题、段落、链接、列表、代码块等结构。"""
        return await self._require_page().get_text()

    @tool
    async def get_content(self) -> str:
        """返回页面的完整无障碍树视图，包含所有节点（交互+内容+文本），含层级缩进和 @eN 引用标记。

        用于理解页面整体结构和内容。输出量大但信息最全，能看到标题、段落、静态文本等 snapshot 中缺失的内容。
        建议阅读页面时首先调用此工具，需要操作具体元素时再使用 snapshot。"""
        return await self._require_page().get_content()

    @tool
    async def screenshot(self, ref: str | None = None) -> str:
        """对当前页面或指定元素截图，返回 base64 编码的 PNG 图片数据。

        Args:
            ref: 元素引用（如 @e1），不传则截全页
        """
        return await self._require_page().screenshot(ref)

    # ── interaction ──

    @tool
    async def click(self, ref: str) -> str:
        """点击页面上由 snapshot 返回的某个元素。

        Args:
            ref: 元素引用（如 @e1）
        """
        await self._require_page().click(ref)
        return f'已点击 {ref}'

    @tool
    async def scroll(self, ref: str | None = None, distance: int | None = None) -> str:
        """模拟鼠标滚轮滚动。不传参数则向下翻一屏。

        Args:
            ref: 元素引用（如 @e1），滚动到该元素中心位置
            distance: 滚动像素距离，正数向下负数向上
        """
        await self._require_page().scroll(ref, distance)
        if ref:
            return f'已滚动到 {ref}'
        if distance is not None:
            return f'已滚动 {distance}px'
        return '已向下滚动一屏'

    @tool
    async def fill(self, ref: str, text: str) -> str:
        """向表单元素填充文本。

        Args:
            ref: 元素引用（如 @e1）
            text: 要填入的文本
        """
        await self._require_page().fill(ref, text)
        return f'已在 {ref} 填入: {text}'

    # ── tool introspection ──

    def _get_tool_methods(self):
        for name, method in type(self).__dict__.items():
            if name.startswith('_'):
                continue
            if callable(method) and getattr(method, '_is_tool', False):
                yield getattr(self, name)

    @property
    def schemas(self) -> list[dict]:
        """返回所有工具的 MCP/OpenAI 格式 schema 列表。"""
        return [
            {
                'name': m.__name__,
                'description': m._tool_schema['description'],
                'inputSchema': m._tool_schema['inputSchema'],
            }
            for m in self._get_tool_methods()
        ]

    async def call(self, name: str, **kwargs) -> str:
        """按名称调用工具。"""
        method = getattr(self, name, None)
        if method is None or not getattr(method, '_is_tool', False):
            _logger.error("call: 未知工具 %s", name)
            raise ValueError(f'未知工具: {name}')
        _logger.info("call: %s %s", name, kwargs)
        try:
            result = await method(**kwargs)
            return result
        except Exception:
            _logger.error("call: %s 执行失败", name, exc_info=True)
            raise

    def as_langchain_tools(self) -> list:
        """将工具转换为 LangChain StructuredTool 列表。

        需要安装 langchain-core 和 pydantic。
        """
        try:
            from langchain_core.tools import StructuredTool  # type: ignore[import-not-found]
            from pydantic import Field, create_model  # type: ignore[import-not-found]
        except ImportError as e:
            raise ImportError(
                '需要安装 langchain-core 和 pydantic: pip install langchain-core pydantic'
            ) from e

        lc_tools = []
        for method in self._get_tool_methods():
            sig = inspect.signature(method.__func__)
            fields: dict[str, Any] = {}
            for name, param in sig.parameters.items():
                if name == 'self':
                    continue
                ann = param.annotation if param.annotation is not inspect.Parameter.empty else str
                desc = method._tool_schema['inputSchema']['properties'].get(name, {}).get('description', '')
                if param.default is not inspect.Parameter.empty:
                    fields[name] = (ann, Field(default=param.default, description=desc))
                else:
                    fields[name] = (ann, Field(description=desc))

            if fields:
                args_model = create_model(f'{method.__name__}_input', **fields)
            else:
                args_model = None

            lc_tools.append(StructuredTool(
                name=method.__name__,
                description=method._tool_schema['description'],
                coroutine=method,
                args_schema=args_model,
            ))
        return lc_tools

    # ── context manager ──

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.close()
            self._client = None
            self._page = None


if __name__ == '__main__':
    import asyncio


    async def main():
        bt = BrowserTools()
        # await bt.connect()
        for i in bt.as_langchain_tools():
            print(i)


    asyncio.run(main())
