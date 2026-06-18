## 一、基础说明
1. CDP（Chrome DevTools Protocol）采用**分域管理**，每个 `域.Domain.method` 是标准调用格式，全部通过 WebSocket 发送 JSON 报文通信；
2. 通用报文模板（所有方法统一格式）
```json
{
  "id": 1,          // 自增唯一请求ID，用于匹配返回响应
  "method": "域.方法名",
  "params": {}      // 当前方法所需入参，无参传空对象
}
```
3. 前置通用规则：**有些域必须先调用 `域.enable` 开启，否则接口无返回/报错**。**注意**调用`域.enable` 后很可能被反爬手段检测。
4. 完整CDP报文示例（Runtime.callFunctionOn）
```json
// 发送WebSocket报文：
{
  "id": 10,
  "method": "Runtime.callFunctionOn",
  "params": {
    "objectId": "{injectedScriptId:1,remoteObjectId:23}",
    "functionDeclaration": "function(offset){this.scrollTop = offset}",
    "arguments": [{"value": 2000}],
    "returnByValue": true
  }
}
```

## 二、接口核心区别速查表
1. Runtime.evaluate
    - 全局执行脚本，代码简短、无需操作DOM对象时首选；
2. Runtime.callFunctionOn
    - 绑定指定DOM/JS对象执行方法，适合精细化元素操作、函数传参；
3. DOM.resolveNode
    - 桥梁接口：DOM层节点ID ↔ Runtime层objectId，是DOM域和Runtime域联动关键；
4. Accessibility.getFullAXTree
    - 不依赖传统DOM，获取语义化页面树，适合爬虫提取文本；
5. Page.navigate
    - 唯一页面加载跳转接口，控制浏览器页面访问；
6. Accessibility.enable
    - 无障碍树开关，仅搭配AXTree接口使用。


## 三、5个域以及对应方法
### 1. Runtime 域（JS 运行时、执行页面脚本核心）
负责页面 JS 上下文执行、对象操作、函数调用，滚动、数据提取高频使用

| 方法 | 全称 | 作用 | 入参示例 | 返回说明 | 使用场景 |
|------|------|------|----------|----------|----------|
| Runtime.evaluate | 表达式执行 | 在页面全局上下文执行任意 JS 代码 | `{"expression":"document.body.scrollHeight","returnByValue":true}` | 返回 JS 执行结果，returnByValue=true 直接拿到序列化值 | 获取页面高度、滚动、读取全局变量、简单JS逻辑 |
| Runtime.callFunctionOn | 调用指定对象上的函数 | 精准调用某个DOM/JS对象的方法，支持传参，比 evaluate 更可控 | `{"objectId":"xxx","functionDeclaration":"function(){return this.scrollTop}","returnByValue":true}` | 指定对象函数返回值 | 操作元素实例方法、传递参数执行DOM方法、隔离上下文执行 |

**关键区分 Runtime.evaluate vs Runtime.callFunctionOn**
1. `evaluate`：全局作用域执行一段脚本，简单读写优先用；
2. `callFunctionOn`：必须传入 `objectId`（DOM对象/JS对象唯一标识），针对特定实例调用方法，适合精细操作元素。

---
### 2. Page 域（页面生命周期、跳转、页面基础操作）
页面加载、导航、加载事件、页面截图、页面开关

| 方法 | 全称 | 作用 | 入参示例 | 使用场景 |
|------|------|------|----------|----------|
| Page.navigate | 页面跳转 | 加载目标URL，刷新/打开新页面 | `{"url":"https://www.xxx.com"}` | 初始化访问目标网页 |
| Page.enable | 启用Page域 | 必须前置调用，否则Page下所有接口失效 | `{}` | 程序启动第一步初始化 |

补充配套Page滚动相关（上文滚动用到）：
- Page.getLayoutMetrics：获取视口、文档宽高（精准替代JS获取页面尺寸）
- Page.reload：页面刷新

---
### 3. Accessibility 域（无障碍树，获取页面完整可访问节点）
爬虫/页面元素结构化提取专用

| 方法 | 全称 | 作用 | 入参 | 使用场景 |
|------|------|------|------|----------|
| Accessibility.enable | 开启无障碍树采集 | 前置依赖，不开启无法获取AXTree | `{}` | 解析页面语义化节点、无障碍标签、文本内容 |
| Accessibility.getFullAXTree | 获取完整无障碍DOM树 | 返回页面全部可访问节点树结构 | `{}` | 抓取页面文本、按钮/输入框语义信息、低干扰页面解析 |

---
### 4. DOM 域（原生DOM节点操作、节点解析、节点ID转换）
DOM节点查询、定位、对象ID转换，衔接 Runtime.callFunctionOn

| 方法 | 全称 | 作用 | 入参示例 | 使用场景 |
|------|------|------|----------|----------|
| DOM.resolveNode | 将DOM后端节点ID转为Runtime对象ID | 把DOM.NodeId转objectId，供给callFunctionOn调用元素方法 | `{"backendNodeId":123}` | 先DOM查询节点，再对节点执行JS函数 |

配套高频DOM域方法补充：
- DOM.getDocument：获取页面根文档节点（拿到根backendNodeId）
- DOM.querySelector：根据选择器查找元素节点

### 5. Input 域（上文滚动逻辑用到，配套参考）
输入、手势、滚动模拟

| 方法 | 作用 |
|------|------|
| Input.enable | 启用输入域，滚动手势前置 |
| Input.synthesizeScrollGesture | 合成原生触摸/鼠标滚动手势，分段平滑滚动页面 |

## 四、调用流程示例
需求：打开网页 → 获取完整无障碍树 → 获取body节点 → 调用节点scroll方法滚动页面
```python
# 1. 初始化开启基础域
await cdp.send_cmd("Page.enable")
await cdp.send_cmd("Accessibility.enable")
await cdp.send_cmd("DOM.enable")
await cdp.send_cmd("Input.enable")

# 2. 跳转页面
await cdp.send_cmd("Page.navigate", {"url": "https://target.com"})

# 3. 获取完整无障碍树
ax_tree = await cdp.send_cmd("Accessibility.getFullAXTree")

# 4. DOM获取根文档，查询body节点
doc = await cdp.send_cmd("DOM.getDocument")
body_node = await cdp.send_cmd("DOM.querySelector", {"nodeId": doc["result"]["root"]["nodeId"], "selector": "body"})

# 5. 转换节点ID为Runtime objectId（DOM.resolveNode）
resolve_res = await cdp.send_cmd("DOM.resolveNode", {"backendNodeId": body_node["result"]["backendNodeId"]})
obj_id = resolve_res["result"]["object"]["objectId"]

# 6. callFunctionOn 调用body滚动方法
await cdp.send_cmd("Runtime.callFunctionOn", {
    "objectId": obj_id,
    "functionDeclaration": "function(){this.scrollTop = this.scrollHeight}",
    "returnByValue": True
})

# 简易方案：Runtime.evaluate 直接执行滚动JS
await cdp.send_cmd("Runtime.evaluate", {
    "expression": "window.scrollTo(0, document.body.scrollHeight)",
    "returnByValue": True
})
```

## 五、补充文档规范说明
1. 所有接口均为**标准CDP官方协议**，Chrome、Edge、Chromium内核浏览器通用；
2. 协议无第三方封装，原生WebSocket直接收发JSON即可调用；
3. 域为层级隔离设计，互不干扰，按需enable节省性能；
4. 所有响应报文会携带对应请求id，用于区分多异步指令返回数据。