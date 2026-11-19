"""Local web server: serves the stage, the WebSocket (see docs/protocol.md),
calibration patterns and the debug image streams. It runs asyncio in its own
thread; the engine talks to it through the thread-safe methods below."""
import asyncio
import json
import queue
import threading
import time
from pathlib import Path

import cv2
from aiohttp import WSMsgType, web

STAGES = ["camera", "rectified", "predicted", "residual", "mask", "overlay"]  # debug images, in pipeline order
WEB_DIR = Path(__file__).parent.parent / "web" / "dist"

# Shown only when the real stage has not been built: enough to calibrate.
FALLBACK_PAGE = """<!doctype html><meta charset=utf-8><title>VisionTouch</title>
<style>html,body{margin:0;height:100%;background:#fff;overflow:hidden;font:28px system-ui}
img{position:fixed;inset:0;width:100vw;height:100vh;display:none}</style>
<p style="padding:2em">VisionTouch engine is running. Build the stage: <code>cd web && pnpm build</code></p><img id=p>
<script>
const p = document.getElementById('p');
function connect() {
  const ws = new WebSocket(`ws://${location.host}/ws`);
  const hello = () => ws.send(JSON.stringify({t: 'hello', w: innerWidth, h: innerHeight}));
  ws.onopen = hello; onresize = hello; ws.onclose = () => setTimeout(connect, 500);
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.t !== 'pattern') return;
    const done = () => requestAnimationFrame(() => requestAnimationFrame(() =>
      ws.send(JSON.stringify({t: 'pattern_shown', id: m.id}))));
    if (!m.url) { p.style.display = 'none'; done(); return; }
    p.onload = () => { p.style.display = 'block'; done(); };
    p.src = m.url;
  };
}
connect();
</script>"""


class Server:
    def __init__(self, port=8765):
        self.port = port
        self.inbox = queue.Queue()  # messages from the stage: hello, cmd, log
        self.window = None  # (w, h) of the stage window, from its last hello
        self._clients = set()
        self._pattern = (0, None)  # (id, png bytes)
        self._shown = threading.Event()
        self._debug = {}  # stage name -> newest JPEG bytes
        self.viewers = 0  # open debug streams; the engine skips debug images when nobody watches
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        self._ready.wait()

    def _run(self):
        asyncio.set_event_loop(self._loop)
        app = web.Application(client_max_size=32 * 2 ** 20)
        app.add_routes([
            web.get("/ws", self._ws),
            web.get("/pattern/{id}.png", self._get_pattern),
            web.get("/debug/stages", lambda r: web.json_response(STAGES)),
            web.get("/debug/{name}.mjpg", self._mjpeg),
            web.post("/save/{name}.png", self._save),
        ])
        if WEB_DIR.exists():
            app.add_routes([web.get("/", lambda r: web.FileResponse(WEB_DIR / "index.html")), web.static("/", WEB_DIR)])
        else:
            app.add_routes([web.get("/", lambda r: web.Response(text=FALLBACK_PAGE, content_type="text/html"))])
        runner = web.AppRunner(app)
        self._loop.run_until_complete(runner.setup())
        self._loop.run_until_complete(web.TCPSite(runner, "127.0.0.1", self.port).start())
        self._ready.set()
        self._loop.run_forever()

    # --- called from the engine thread ---

    def send(self, message):
        """Broadcast one protocol message to every connected stage."""
        text = json.dumps(message)
        for ws in list(self._clients):
            asyncio.run_coroutine_threadsafe(ws.send_str(text), self._loop)

    def show(self, image, timeout=3.0):
        """Project `image` full-window (None removes it) and block until the
        stage reports it painted. Returns False if no stage answered."""
        number = self._pattern[0] + 1
        png = None if image is None else cv2.imencode(".png", image)[1].tobytes()
        self._pattern = (number, png)
        self._shown.clear()
        self.send({"t": "pattern", "id": number, "url": png and f"/pattern/{number}.png"})
        return self._shown.wait(timeout)

    def debug(self, name, image):
        """Publish a pipeline stage image for the debug view."""
        self._debug[name] = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 70])[1].tobytes()

    def wait_for_stage(self, timeout=15.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end and not self.window:
            time.sleep(0.05)
        return self.window

    # --- request handlers (asyncio thread) ---

    async def _ws(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._clients.add(ws)
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                m = json.loads(msg.data)
                if m.get("t") == "hello":
                    self.window = (m["w"], m["h"])
                elif m.get("t") == "pattern_shown":
                    if m.get("id") == self._pattern[0]:
                        self._shown.set()
                    continue
                self.inbox.put(m)
        finally:
            self._clients.discard(ws)
        return ws

    async def _get_pattern(self, request):
        number, png = self._pattern
        if png is None or request.match_info["id"] != str(number):
            raise web.HTTPNotFound()
        return web.Response(body=png, content_type="image/png", headers={"Cache-Control": "no-store"})

    async def _save(self, request):
        """Store a picture sent by the stage (the Board's Save button)."""
        folder = Path.home() / "Pictures" / "VisionTouch"
        folder.mkdir(parents=True, exist_ok=True)
        name = "".join(c for c in request.match_info["name"] if c.isalnum() or c in "-_") or "picture"
        path = folder / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}.png"
        path.write_bytes(await request.read())
        return web.json_response({"path": str(path)})

    async def _mjpeg(self, request):
        name = request.match_info["name"]
        if name not in STAGES:
            raise web.HTTPNotFound()
        response = web.StreamResponse(headers={"Content-Type": "multipart/x-mixed-replace; boundary=frame"})
        await response.prepare(request)
        last = None
        self.viewers += 1
        try:
            while True:
                jpeg = self._debug.get(name)
                if jpeg is not None and jpeg is not last:
                    last = jpeg
                    await response.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n")
                await asyncio.sleep(1 / 15)
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            self.viewers -= 1
        return response
