"""The whole engine against a simulated projector and camera.

No hardware needed: the "camera" is a perspective view of whatever the engine
asks the stage to show, with exposure gain, rainbow banding and noise added.
Run with pytest, or directly: python tests/test_simulated_rig.py
"""
import os
import queue
import sys
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ["VISIONTOUCH_HOME"] = tempfile.mkdtemp()  # keep test calibration out of the real one

from visiontouch.engine import Engine  # noqa: E402
from visiontouch.predict import SCREEN_SCALE  # noqa: E402

W, H = 1280, 720  # screen
CAMERA = (1280, 720)
# Screen -> camera: a slanted projector seen by a camera off to one side.
VIEW = cv2.getPerspectiveTransform(np.float32([[0, 0], [W, 0], [W, H], [0, H]]),
                                   np.float32([[250, 110], [1010, 150], [980, 600], [280, 560]]))


class SimulatedRig:
    """Plays three roles for the engine: stage server, camera and screen."""

    name = "simulated"

    def __init__(self):
        self.inbox, self.window, self.sent = queue.Queue(), (W, H), []
        self.size, self.origin = (W, H), (0, 0)
        self.pattern = None  # what the engine asked the stage to show
        self.content = np.full((H, W, 3), 235, np.uint8)  # what the stage shows otherwise
        self.in_front = None  # mask of something between projector and wall (content pixels)
        self.frames, self.rng = 0, np.random.default_rng(0)

    # stage server
    def show(self, image):
        self.pattern = image
        return True

    def send(self, message):
        self.sent.append(message)

    def debug(self, name, image):
        pass

    # screen capture
    def _on_screen(self):
        return self.content if self.pattern is None else self.pattern

    def at(self, when, window=0.12):
        return cv2.resize(self._on_screen(), None, fx=SCREEN_SCALE, fy=SCREEN_SCALE, interpolation=cv2.INTER_AREA), None

    def latest(self):
        return time.monotonic(), self.at(0)[0]

    # camera
    def read(self, newer_than=0, timeout=2.0):
        picture = self._on_screen().astype(np.float32)
        if self.in_front is not None and self.pattern is None:
            picture[self.in_front > 0] *= 0.08  # a shadow: almost no projector light
        view = cv2.warpPerspective(picture, VIEW, CAMERA, borderValue=(25, 25, 25))
        view = 255 * (view / 255) ** 0.8 * [0.95, 1.0, 0.92]  # camera tone curve and colour cast
        rows = np.arange(CAMERA[1])[:, None, None] / 40 + self.frames  # rainbow banding moves every frame
        view = view * (1 + 0.04 * np.sin(rows + np.array([0, 2.1, 4.2]))) + self.rng.normal(0, 1.5, view.shape)
        self.frames += 1
        time.sleep(0.005)
        return np.clip(view, 0, 255).astype(np.uint8), time.monotonic(), self.frames

    def close(self):
        pass


def test_calibrate_then_find_a_fingertip():
    rig = SimulatedRig()
    engine = Engine(rig, camera=rig, screen=rig, landmarks=False)
    assert engine.calibrate(), engine.message
    assert "Calibrated" in engine.message
    # The calibration must have recovered the true geometry.
    centre = cv2.perspectiveTransform(np.float32([[[W / 2, H / 2]]]), VIEW)[0, 0]
    found = cv2.perspectiveTransform(centre[None, None], engine.predictor.cam_to_screen)[0, 0]
    assert np.linalg.norm(found - [W / 2, H / 2]) < 3, found

    def pointers_after(frames):
        engine.tracker.pointers.clear()
        return [engine.step() for _ in range(frames)][-1]

    assert pointers_after(8) == [], "a hand was reported on an empty screen"

    # An arm reaching in from the bottom edge of the corrected picture, fingertip at (0.6, 0.35).
    tip = np.array([0.6 * W, 0.35 * H])
    arm = np.zeros((H, W), np.uint8)
    cv2.line(arm, (int(0.7 * W), H + 20), (int(tip[0] + 14), int(tip[1] + 60)), 255, 60)
    cv2.line(arm, (int(tip[0] + 14), int(tip[1] + 60)), (int(tip[0]), int(tip[1] + 9)), 255, 18)
    blank = np.full((H, W, 3), 235, np.uint8)
    rig.content = cv2.warpPerspective(blank, engine.warp, (W, H))  # as the stage draws it under keystone
    rig.in_front = cv2.warpPerspective(arm, engine.warp, (W, H))
    pointers = pointers_after(10)
    assert len(pointers) == 1, pointers
    error = np.hypot(pointers[0]["x"] * W - tip[0], pointers[0]["y"] * H - tip[1])
    assert error < 0.015 * W, f"fingertip off by {error:.1f} px"

    # Holding still long enough gives one dwell click.
    downs = []
    end = time.monotonic() + 1.3
    while time.monotonic() < end:
        downs.append(engine.step()[0]["down"])
    assert any(downs) and not downs[0], "no dwell click"


if __name__ == "__main__":
    test_calibrate_then_find_a_fingertip()
    print("ok")
