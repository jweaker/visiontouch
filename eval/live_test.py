"""End-to-end test on the real rig, with nobody in the room.

    python -m eval.live_test [camera] [--washed] [--pictures white balloons ...]

Calibrates for real, then projects test pictures with a synthetic hand painted
in while the engine is told the picture has no hand. The engine therefore has
to find the hand through the real projector and camera, and its fingertip can
be compared with the known position. Clean pictures measure false alarms.
"""
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from eval.content import H, W, contents, fake_hand, occlude
from visiontouch.app import run
from visiontouch.engine import Engine

ARGS = sys.argv[1:]
PICTURES = [a for a in ARGS[ARGS.index("--pictures") + 1:] if not a.startswith("--")] if "--pictures" in ARGS else ["white", "pastel", "light", "board", "balloons", "slide_light", "text", "mid"]
CAMERA = ARGS[0] if ARGS and not ARGS[0].startswith("--") else "0"
OUT = Path("runs/live")


class PretendScreen:
    """Stands in for screen capture: keeps reporting an earlier screenshot as
    'on screen', while the stage goes on to show something else."""

    def __init__(self, real):
        self.size, self.origin, self.real, self.picture = real.size, real.origin, real, None

    def freeze(self, engine, picture):
        """Remember what is on screen now. `picture` is what the stage was asked
        to show; wherever the screenshot differs, the operating system has put
        something on top (a dialog, a notification), and the engine is told to
        disregard that spot: a translucent dialog changes its look with the
        picture behind it and would count as an object in these tests."""
        self.picture = self.real.latest()[1]
        wanted = cv2.resize(picture, self.picture.shape[1::-1], interpolation=cv2.INTER_AREA)
        foreign = (cv2.absdiff(self.picture, wanted).max(2) > 10).astype(np.uint8)
        foreign = cv2.morphologyEx(foreign, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        foreign = cv2.morphologyEx(foreign, cv2.MORPH_CLOSE, np.ones((41, 41), np.uint8))
        blind = cv2.dilate(engine.predictor.warp_screen(foreign), np.ones((31, 31), np.uint8)) > 0
        engine.blind = blind if blind.any() else None
        # Synthetic hands are kept clear of these spots (see `clear_of`).
        self.foreign = cv2.resize(cv2.dilate(foreign, np.ones((25, 25), np.uint8)), self.size, interpolation=cv2.INTER_NEAREST)
        return float(blind.mean())

    def clear_of(self, make_hand):
        """Draw synthetic hands until one does not cross a disregarded spot."""
        for _ in range(100):
            mask, tip = make_hand()
            if not (mask[self.foreign > 0] > 0).any():
                break
        return mask, tip

    def at(self, when, window=0.12):
        return self.picture, None

    def latest(self):
        return self.real.latest()


def main(server):
    assert server.wait_for_stage(), "stage window did not connect"
    server.viewers = 1  # keep debug images coming: this test saves them
    OUT.mkdir(parents=True, exist_ok=True)
    if "--washed" in ARGS:  # imitate a weak projector in a lit room: grey blacks, dim whites
        server.view.evaluate_js("document.documentElement.style.filter = 'contrast(0.45) brightness(0.85)'")
    engine = Engine(server, CAMERA)
    assert engine.calibrate(), engine.message
    print(engine.message, flush=True)
    engine.keystone = False  # this test works in plain screen pixels
    engine._send_warp()
    real, pretend = engine.screen, PretendScreen(engine.screen)
    rng = np.random.default_rng(3)
    pictures = contents()
    report, times = [], []

    def run_frames(seconds, settle=1.0):
        time.sleep(settle)
        engine.tracker.pointers.clear()
        seen, end = [], time.monotonic() + seconds
        while time.monotonic() < end:
            start = time.perf_counter()
            pointers = engine.step()
            if pointers is not None:
                times.append(time.perf_counter() - start)
                seen.append(pointers)
        return seen

    for name in PICTURES:
        picture = pictures[name]
        # 1. Real screen capture, nothing in front: any pointer is a false alarm.
        engine.screen, engine.blind = real, None
        server.show(picture)
        clean = run_frames(2.0)
        false_alarms = np.mean([len(p) > 0 for p in clean])
        row = {"picture": name, "false_alarm_frames": float(false_alarms)}
        # 2. Synthetic shadow and synthetic lit hand at random places.
        row["disregarded_area"] = pretend.freeze(engine, picture)  # the clean picture is still up
        engine.screen = pretend
        for kind in ("shadow", "hand"):
            errors, found = [], []
            for trial in range(3):
                mask, tip = pretend.clear_of(lambda: fake_hand(rng))
                server.show(occlude(picture, mask, kind))
                frames = run_frames(1.0, settle=0.8)
                hits = [p[0] for p in frames if p]
                found.append(len(hits) / max(len(frames), 1))
                errors += [np.hypot(p["x"] * W - tip[0], p["y"] * H - tip[1]) for p in hits]
            row[kind] = {"found": float(np.mean(found)), "median_error_px": float(np.median(errors)) if errors else None,
                         "p90_error_px": float(np.percentile(errors, 90)) if errors else None}
        report.append(row)
        print(json.dumps(row), flush=True)
        for stage in ("overlay", "residual"):
            (OUT / f"{name}_{stage}.jpg").write_bytes(server._debug[stage])
    server.show(None)
    summary = {"camera": CAMERA, "calibration": engine.message, "ms_per_frame": 1000 * float(np.median(times)), "pictures": report}
    name = f"report_{CAMERA.split(':')[0]}{'_washed' if '--washed' in ARGS else ''}.json"
    (OUT / name).write_text(json.dumps(summary, indent=1))
    print("median step time %.1f ms" % summary["ms_per_frame"])
    engine.camera.close()


if __name__ == "__main__":
    run(main)
