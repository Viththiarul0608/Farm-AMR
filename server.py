"""Farm AMR server — Python standard library only (no pip install needed).

  * runs the farm engine continuously (20 ticks/s), with or without any browser open
  * streams live robot positions to every open dashboard over WebSocket (10 updates/s)
  * saves state to data/state.json every 3 s and on shutdown, and resumes from it on restart

Run:   python3 server.py            → http://localhost:3000
       PORT=8080 python3 server.py
"""
import asyncio
import base64
import hashlib
import json
import mimetypes
import os
import signal
import struct
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

import world
from engine import FarmEngine

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / 'public'
PORT = int(os.environ.get('PORT', '9000'))
HOST = os.environ.get('HOST', '0.0.0.0')
DATA_FILE = Path(os.environ.get('DATA_FILE', ROOT / 'data' / 'state.json'))
WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
WORLD_JS = world.client_js().encode()

engine = FarmEngine()
clients = set()
dirty = True


# ---------------- persistence ----------------
def load_state():
    try:
        return json.loads(DATA_FILE.read_text())
    except (OSError, ValueError):
        return None


def save_state():
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(engine.export_state()))
    os.replace(tmp, DATA_FILE)


# ---------------- WebSocket client ----------------
class WSClient:
    def __init__(self, reader, writer):
        self.reader, self.writer, self.open = reader, writer, True

    def send(self, obj):
        if not self.open:
            return
        if self.writer.transport.get_write_buffer_size() > 2_000_000:   # very slow client: drop it
            self.close()
            return
        data = json.dumps(obj, separators=(',', ':')).encode()
        n = len(data)
        if n < 126:
            head = struct.pack('!BB', 0x81, n)
        elif n < 65536:
            head = struct.pack('!BBH', 0x81, 126, n)
        else:
            head = struct.pack('!BBQ', 0x81, 127, n)
        try:
            self.writer.write(head + data)
        except Exception:
            self.close()

    def close(self):
        if self.open:
            self.open = False
            clients.discard(self)
            try:
                self.writer.close()
            except Exception:
                pass

    async def frames(self):
        """Yield complete text messages from the browser."""
        parts = []
        while self.open:
            h = await self.reader.readexactly(2)
            fin, op = h[0] & 0x80, h[0] & 0x0F
            masked, n = h[1] & 0x80, h[1] & 0x7F
            if n == 126:
                n = struct.unpack('!H', await self.reader.readexactly(2))[0]
            elif n == 127:
                n = struct.unpack('!Q', await self.reader.readexactly(8))[0]
            if n > 1_000_000:
                return
            mask = await self.reader.readexactly(4) if masked else b'\0\0\0\0'
            payload = bytearray(await self.reader.readexactly(n))
            for i in range(n):
                payload[i] ^= mask[i & 3]
            if op == 0x8:          # close
                return
            if op == 0x9:          # ping -> pong
                self.writer.write(struct.pack('!BB', 0x8A, len(payload)) + bytes(payload))
                continue
            if op in (0x1, 0x0):
                parts.append(bytes(payload))
                if fin:
                    yield b''.join(parts).decode('utf-8', 'replace')
                    parts = []


async def websocket(reader, writer, headers):
    key = headers.get('sec-websocket-key', '')
    accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
    writer.write(('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                  f'Sec-WebSocket-Accept: {accept}\r\n\r\n').encode())
    await writer.drain()
    c = WSClient(reader, writer)
    clients.add(c)
    c.send({'type': 'hello', 'data': engine.data_state(), 'feed': engine.feed(), 'live': engine.snapshot()})
    try:
        async for raw in c.frames():
            try:
                m = json.loads(raw)
            except ValueError:
                continue
            if isinstance(m, dict) and m.get('type') == 'cmd':
                try:
                    r = engine.cmd(m.get('cmd') or {})
                except Exception as e:
                    print('command failed:', e)
                    r = {'ok': False, 'msg': f'Server error: {e}'}
                c.send({'type': 'result', 'reqId': m.get('reqId'), **r})
    except (asyncio.IncompleteReadError, ConnectionError):
        pass
    finally:
        c.close()


# ---------------- HTTP ----------------
def respond(writer, code, body, ctype='application/json', extra=''):
    if isinstance(body, (dict, list)):
        body = json.dumps(body).encode()
    elif isinstance(body, str):
        body = body.encode()
    reason = {200: 'OK', 400: 'Bad Request', 403: 'Forbidden', 404: 'Not Found'}.get(code, 'OK')
    writer.write((f'HTTP/1.1 {code} {reason}\r\nContent-Type: {ctype}\r\nContent-Length: {len(body)}\r\n'
                  f'Cache-Control: no-cache\r\nConnection: close\r\n{extra}\r\n').encode() + body)


async def handle(reader, writer):
    try:
        head = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), timeout=15)
    except Exception:
        writer.close()
        return
    lines = head.decode('latin-1').split('\r\n')
    try:
        method, target, _ = lines[0].split(' ', 2)
    except ValueError:
        writer.close()
        return
    headers = {}
    for line in lines[1:]:
        if ':' in line:
            k, v = line.split(':', 1)
            headers[k.strip().lower()] = v.strip()
    path = urlparse(target).path

    if path == '/ws' and headers.get('upgrade', '').lower() == 'websocket':
        await websocket(reader, writer, headers)
        return

    body = b''
    if int(headers.get('content-length', '0') or 0) > 0:
        body = await reader.readexactly(min(int(headers['content-length']), 100_000))

    def payload():
        try:
            return json.loads(body or b'{}')
        except ValueError:
            return None

    global dirty
    if path == '/api/health':
        respond(writer, 200, {'ok': True, 'clients': len(clients), 'time': int(time.time() * 1000)})
    elif path == '/api/state' and method == 'GET':
        respond(writer, 200, {'data': engine.data_state(), 'live': engine.snapshot()})
    elif path == '/api/tasks' and method == 'POST':
        p = payload()
        respond(writer, 200 if p is not None else 400, engine.cmd({**p, 'op': 'task.create'}) if p is not None else {'ok': False, 'msg': 'Invalid JSON'})
    elif path.startswith('/api/tasks/') and path.endswith('/cancel') and method == 'POST':
        respond(writer, 200, engine.cmd({'op': 'task.cancel', 'taskId': path.split('/')[3]}))
    elif path == '/api/cmd' and method == 'POST':
        p = payload()
        respond(writer, 200 if p is not None else 400, engine.cmd(p) if p is not None else {'ok': False, 'msg': 'Invalid JSON'})
    elif path.startswith('/api/'):
        respond(writer, 404, {'ok': False, 'msg': 'Not found'})
    elif path == '/world.js':
        respond(writer, 200, WORLD_JS, 'text/javascript; charset=utf-8')
    else:
        f = (PUBLIC / ('index.html' if path == '/' else unquote(path).lstrip('/'))).resolve()
        if PUBLIC not in f.parents and f != PUBLIC:
            respond(writer, 403, b'', 'text/plain')
        elif f.is_file():
            ctype = mimetypes.guess_type(str(f))[0] or 'application/octet-stream'
            if ctype.startswith('text/') or ctype.endswith('javascript'):
                ctype += '; charset=utf-8'
            respond(writer, 200, f.read_bytes(), ctype)
        else:
            respond(writer, 404, 'Not found', 'text/plain')
    try:
        await writer.drain()
    finally:
        writer.close()


# ---------------- loops ----------------
async def sim_loop():
    last = time.monotonic()
    while True:
        await asyncio.sleep(0.05)
        now = time.monotonic()
        try:
            engine.step(min(0.5, now - last))
        except Exception as e:
            print('engine step failed:', e)
        last = now


async def stream_loop():
    global dirty
    while True:
        await asyncio.sleep(0.1)
        if not clients:
            continue
        live = {'type': 'live', 'live': engine.snapshot()}
        data = {'type': 'data', 'data': engine.data_state()} if dirty else None
        dirty = False
        for c in list(clients):
            c.send(live)
            if data:
                c.send(data)


async def save_loop():
    while True:
        await asyncio.sleep(3)
        try:
            save_state()
        except Exception as e:
            print('save failed:', e)


def on_log(e):
    for c in list(clients):
        c.send({'type': 'log', 'entry': e})
    print(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(e['t'] / 1000)), e['msg'], flush=True)


def on_changed(_):
    global dirty
    dirty = True


async def main():
    engine.on('log', on_log)
    engine.on('changed', on_changed)
    engine.init(load_state())
    server = await asyncio.start_server(handle, HOST, PORT)
    print(f'Farm AMR server (Python) running → http://localhost:{PORT}   (state file: {DATA_FILE})', flush=True)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):   # Windows
            pass
    tasks = [asyncio.create_task(x()) for x in (sim_loop, stream_loop, save_loop)]
    async with server:
        try:
            await stop.wait()
        finally:
            for t in tasks:
                t.cancel()
            save_state()
            print('State saved. Bye.')


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        if engine.S:
            save_state()
