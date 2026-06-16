"""CDP proxy: 9223 → 9222, 记录所有 WebSocket 消息
Usage: uv run proxy.py
Then: agent-browser --cdp 9223 snapshot -i
"""
import asyncio
import json
import struct


CDP_DST = ('127.0.0.1', 9222)
PROXY_PORT = 9223


async def proxy_ws(reader, writer, label):
    buf = bytearray()
    while True:
        data = await reader.read(65536)
        if not data:
            break
        buf.extend(data)
        while len(buf) >= 2:
            if buf[0] & 0x80:  # masked frame from client
                break
            if len(buf) < 6:
                break
            opcode = buf[0] & 0x0F
            mask = buf[1] & 0x80
            length = buf[1] & 0x7F
            offset = 2
            if length == 126:
                if len(buf) < 4: break
                length = struct.unpack('>H', buf[2:4])[0]
                offset = 4
            elif length == 127:
                if len(buf) < 10: break
                length = struct.unpack('>Q', buf[2:10])[0]
                offset = 10
            if len(buf) < offset + length: break
            payload = bytes(buf[offset:offset + length])
            buf = buf[offset + length:]
            if opcode == 0x01 or opcode == 0x02:  # text or binary
                try:
                    msg = json.loads(payload.decode())
                    method = msg.get('method', '')
                    msg_id = msg.get('id', '')
                    if method:
                        print(f'[{label}] {method}({json.dumps(msg.get("params", {}))[:120]})')
                    elif 'result' in msg:
                        r = msg['result']
                        rstr = json.dumps(r)[:80] if isinstance(r, dict) else str(r)[:80]
                        print(f'[{label}] ← result id={msg_id}: {rstr}')
                except Exception:
                    print(f'[{label}] raw: {payload[:200]}')
            writer.write(data[:offset + length])
            await writer.drain()
            data = data[offset + length:]


async def handle_http(reader, writer):
    req = await reader.read(4096)
    # 转发 HTTP 请求到真实 CDP
    r_reader, r_writer = await asyncio.open_connection(*CDP_DST)
    r_writer.write(req)
    await r_writer.drain()
    resp = await r_reader.read(65536)
    writer.write(resp)
    await writer.drain()
    writer.close()
    await writer.wait_closed()

    # 如果请求的是 WebSocket，开始代理
    if b'Upgrade: websocket' in req:
        c_reader, c_writer = await asyncio.open_connection(*CDP_DST)
        # 重新发送 upgrade 请求
        c_writer.write(req)
        await c_writer.drain()
        resp = await c_reader.read(65536)
        writer.write(resp)
        await writer.drain()
        await asyncio.gather(
            proxy_ws(reader, c_writer, 'AB→'),
            proxy_ws(c_reader, writer, 'AB←'),
        )


async def main():
    server = await asyncio.start_server(handle_http, '127.0.0.1', PROXY_PORT)
    print(f'Proxy listening on 127.0.0.1:{PROXY_PORT} → {CDP_DST[0]}:{CDP_DST[1]}')
    print('Run: agent-browser --cdp 9223 snapshot -i')
    async with server:
        await server.serve_forever()


if __name__ == '__main__':
    asyncio.run(main())
