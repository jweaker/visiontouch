"""Drives the real stage, in the real app window, with a synthetic hand.

    python -m eval.stage_test

No camera involved: pointer messages are sent straight to the stage, as the
engine would send them. Checks that a hand can open the Board, draw, save the
drawing through the engine, change settings, and that desktop mode shrinks the
window and its button brings the stage back.
"""
import json
import sys
import threading
import time
from pathlib import Path

from visiontouch.app import run
from visiontouch.engine import Engine


def main(server):
    assert server.wait_for_stage(), "stage window did not connect"
    js = server.view.evaluate_js
    engine = Engine(server, sys.argv[1] if len(sys.argv) > 1 else "0")
    engine.keystone = False  # plain coordinates: content box = window
    engine._send_warp()
    engine.step = lambda: time.sleep(0.02)  # no camera frames: this test supplies the hand itself
    threading.Thread(target=engine.run, daemon=True).start()  # still answers the stage's commands
    results = {}

    def centre(selector_js):
        """Centre of an element, as content-box fractions."""
        x, y, w, h = js(f"(() => {{ const r = ({selector_js}).getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2, innerWidth, innerHeight] }})()")
        return x / w, y / h

    def hand(x, y, down=False, pose="point"):
        server.send({"t": "pointers", "p": [{"id": 1, "x": x, "y": y, "down": down, "pose": pose}]})
        time.sleep(0.035)

    def tap(x, y):
        for down in (False, False, True, True, False, False):
            hand(x, y, down)

    def gone():
        server.send({"t": "pointers", "p": []})
        time.sleep(0.2)

    js("location.hash = ''")
    time.sleep(1.0)
    tap(*centre("[...document.querySelectorAll('button')].find(b => /Board/.test(b.textContent))"))
    time.sleep(0.8)
    results["hand opens the Board"] = js("location.hash") == "#board"

    # Draw a diagonal stroke with the hand held "down".
    for i in range(30):
        hand(0.3 + 0.012 * i, 0.4 + 0.008 * i, down=i > 2)
    hand(0.66, 0.64)
    gone()
    ink = js("(() => { const c = document.querySelector('.board canvas'); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 0; i < d.length; i += 4) if (d[i] + d[i + 1] + d[i + 2] < 600) n++; return n })()")
    results["drawing leaves ink"] = ink > 500
    # The board asks the engine for hold-to-draw while the hand is over the canvas.
    results["board requests hold-to-draw"] = engine.tracker.hold is True

    before = set((Path.home() / "Pictures" / "VisionTouch").glob("board-*.png"))
    tap(*centre("document.querySelector('[data-act=save]')"))
    time.sleep(1.5)
    new = set((Path.home() / "Pictures" / "VisionTouch").glob("board-*.png")) - before
    results["save stores a PNG through the engine"] = len(new) == 1 and next(iter(new)).stat().st_size > 2000
    for path in new:
        path.unlink()  # leave no test picture behind
    results["toolbar switches back to tap"] = engine.tracker.hold is False
    gone()

    # Home: a hand only has to point at the home button for a second (no press).
    js("location.hash = '#memory'")
    time.sleep(0.8)
    x, y = centre("document.querySelector('#home')")
    for _ in range(45):
        hand(x, y)
    results["pointing at home for a second goes home"] = js("location.hash") in ("", "#")
    gone()

    # Settings: the keystone switch reaches the engine.
    js("location.hash = '#settings'")
    time.sleep(0.8)
    tap(*centre("document.querySelector('[data-keystone]')"))
    time.sleep(0.6)
    results["keystone switch reaches the engine"] = engine.keystone is True
    engine.keystone = False
    engine._send_warp()
    gone()

    # Desktop mode: the window shrinks to a strip whose button brings the stage back.
    engine._handle({"t": "cmd", "name": "mode", "value": "desktop"})
    time.sleep(1.5)
    results["desktop mode shrinks the window"] = server.window[0] < 600 and server.window[1] < 200
    label = js("document.body.innerText")
    results["strip shows the way back"] = "Back to VisionTouch" in (label or "")
    js("[...document.querySelectorAll('button')].find(b => /Back to VisionTouch/.test(b.textContent)).click()")
    time.sleep(4.0)
    results["button returns to the fullscreen stage"] = engine.mode == "apps" and server.window[0] > 1000

    js("location.hash = ''")
    for name, ok in results.items():
        print(("PASS  " if ok else "FAIL  ") + name, flush=True)
    Path("runs/idle").mkdir(parents=True, exist_ok=True)
    Path("runs/idle/stage_test.json").write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    run(main)
