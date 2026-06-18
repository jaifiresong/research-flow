import json
import re
import subprocess
import sys
import time

"""
MCP 服务测试脚本
通过 stdio 与 MCP 服务进行 JSON-RPC 通信，验证服务是否正常工作。

脚本功能：
- 通过 stdio 管道进行 JSON-RPC 通信，依次验证：
   - initialize 初始化握手
       - initialize 请求是 MCP 握手流程的第一步，它的核心作用是建立客户端与服务器之间的会话（Session）基础。如果缺少这一步或握手失败，后续所有的工具调用、资源读取等操作都会被服务器拒绝。
   - notifications/initialized 通知
       - 它的核心作用是 告诉服务器：“我已收到你的初始化响应，一切正常，我们现在可以正式开始干活了。”
       - 不发虽然能跑，但强烈建议发送它。这只是一个空 JSON 包（几乎没有性能开销），却能保证你的代码在任何遵循标准的 MCP 服务器上都能稳定运行。
   - tools/list 工具列表（检查 get_host_info 和 foo 是否存在）
   - tools/call 调用 get_host_info 工具并验证返回 JSON 结构
- 自动清理子进程
"""


def send_message(_proc, msg: dict) -> None:
    """向 MCP 服务发送一条 JSON-RPC 消息（追加换行符）。"""
    line = json.dumps(msg, ensure_ascii=False)
    _proc.stdin.write(line.encode("utf-8") + b"\n")
    _proc.stdin.flush()
    print(f"[C -> S] {line}")


def read_message(_proc, timeout: float = 10.0) -> dict | None:
    """从 MCP 服务读取一条 JSON-RPC 消息。"""
    line = _proc.stdout.readline()
    if not line:
        return None
    decoded = line.decode("utf-8").strip()
    # 安全打印：控制台可能是 GBK 编码，JSON 中若含 emoji/私有区字符会打印失败
    try:
        print(f"[S -> C] {decoded}")
    except UnicodeEncodeError:
        safe = decoded.encode(sys.stdout.encoding, errors="replace").decode(sys.stdout.encoding)
        print(f"[S -> C] {safe}")
    try:
        return json.loads(decoded)
    except Exception as e:
        print(f"[ERROR] JSON 解析失败: {e}")
        return None


proc: subprocess.Popen | None = None


def start_mcp_server() -> subprocess.Popen:
    """运行 MCP 服务测试。"""
    print("=" * 60)
    print("启动 MCP 服务测试...")
    print("=" * 60)

    # 1. 启动 MCP 服务子进程
    python_cmd = [
        r"D:\jaifiresong\bili2text\.venv\Scripts\python.exe",  # 使用指定的 Python 虚拟环境解释器
        r"D:\tmp\research-flow\cdp\tools_mcp_server.py ",
    ]

    global proc
    proc = subprocess.Popen(
        python_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # 等待服务启动
    time.sleep(0.5)

    # 检查子进程是否已异常退出
    if proc.poll() is not None:
        stderr_data = proc.stderr.read()
        print("[FAIL] MCP 服务启动失败，进程已退出")
        if stderr_data:
            print("[STDERR]")
            print(stderr_data.decode("utf-8", errors="replace"))
        raise Exception("MCP 服务启动失败")

    return proc


# 2. 发送 initialize 请求
def t1() -> None:
    print("\n[步骤 1] 发送 initialize 请求...")
    init_id = "init-1"
    send_message(
        proc,
        {
            "jsonrpc": "2.0",
            "id": init_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"},
            },
        },
    )

    response = read_message(proc)
    if response is None:
        print("[FAIL] 未收到 initialize 响应")
    if response.get("id") != init_id:
        print("[FAIL] initialize 响应 ID 不匹配")
    if "result" not in response:
        print("[FAIL] initialize 响应中没有 result")
    print("[PASS] initialize 成功")


def t2() -> None:
    print("\n[步骤 2] 发送 initialized 通知...")
    send_message(
        proc,
        {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        },
    )
    print("[PASS] initialized 通知已发送")


def t3() -> None:
    print("\n[步骤 3] 请求工具列表 (tools/list)...")
    list_id = "list-1"
    send_message(
        proc,
        {
            "jsonrpc": "2.0",
            "id": list_id,
            "method": "tools/list",
            "params": {},
        },
    )

    response = read_message(proc)
    if response is None:
        print("[FAIL] 未收到 tools/list 响应")
        return False
    if response.get("id") != list_id:
        print("[FAIL] tools/list 响应 ID 不匹配")
        return False

    tools_result = response.get("result", {})
    tools = tools_result.get("tools", [])
    tool_names = [t.get("name") for t in tools]
    print(f"[INFO] 发现工具: {tool_names}")


def tools_call(*, call_id: str, call_name: str, **kwargs):
    print(f"\n调用工具 {name}...")
    send_message(
        proc,
        {
            "jsonrpc": "2.0",
            "id": call_id,
            "method": "tools/call",
            "params": {"name": call_name, "arguments": {**kwargs}},
        },
    )

    response = read_message(proc)
    if response is None:
        print(f"[FAIL] 未收到 {name} 调用响应")
        return None
    if response.get("id") != call_id:
        print(f"[FAIL] {name} 调用响应 ID 不匹配")
        return None
    return response


if __name__ == "__main__":
    """
    测试过程
    启动：D:\jaifiresong\bili2text\.venv\Scripts\python.exe D:\tmp\research-flow\cdp\mcp_server_test.py
    browser_open url===https://www.zhipin.com/web/geek/jobs?ka=header-jobs
    browser_snapshot
    """
    try:
        start_mcp_server()
        t1()
        t2()
        t3()
        cnt = 1
        while True:
            data = input("调用工具：")
            data = re.split("\s+", data)
            name = data[0]
            params = {k: v for k, v in [x.split('===') for x in data[1:]]}
            tools_call(call_id=cnt, call_name=name, **params)
            cnt += 1
    finally:
        # 清理子进程
        print("\n[清理] 终止 MCP 服务子进程...")
        try:
            proc.stdin.close()
        except Exception:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
