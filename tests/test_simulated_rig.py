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
DELAY = 0.2  # seconds between drawing a picture and the camera seeing it
TONE = (255 * (np.arange(256) / 255) ** 0.8).astype(np.uint8)  # the camera's tone curve
_rows = np.arange(CAMERA[1], dtype=np.float32)[:, None, None] / 40
BANDS = [1 + 0.04 * np.sin(_rows + phase + np.float32([0, 2.1, 4.2])) for phase in range(7)]
NOISE = [np.random.default_rng(i).normal(0, 1.5, (CAMERA[1], CAMERA[0], 3)).astype(np.float32) for i in range(5)]
# Screen -> camera: a slanted projector seen by a camera off to one side.
VIEW = cv2.getPerspectiveTransform(np.float32([[0, 0], [W, 0], [W, H], [0, H]]),
                                   np.float32([[250, 110], [1010, 150], [980, 600], [280, 560]]))


class SimulatedRig:
    """Plays three roles for the engine: stage server, camera and screen.
    Like a real projector, it shows a picture a little late (`DELAY`)."""

    name = "simulated"

    def __init__(self):
        self.inbox, self.window, self.sent = queue.Queue(), (W, H), []
        self.size, self.origin = (W, H), (0, 0)
        self.timeline = []  # (time, picture, half-size picture) for every change of the screen
        self.pattern = None  # what the engine asked the stage to show
        self.content = np.full((H, W, 3), 235, np.uint8)  # what the stage shows otherwise
        self.in_front = None  # mask of something between projector and wall (content pixels)
        self.frames = 0

    @property
    def content(self):
        return self._content

    @content.setter
    def content(self, picture):
        self._content = picture
        self._note()  # the moment the stage draws something new

    # stage server
    def show(self, image):
        self.pattern = image
        self._note()
        return True

    def send(self, message):
        self.sent.append(message)

    def debug(self, name, image):
        pass

    # screen capture
    def _note(self):
        """Record the picture on screen now, if it changed."""
        now, picture = time.monotonic(), (self._content if self.pattern is None else self.pattern)
        if not self.timeline or self.timeline[-1][1] is not picture:
            small = cv2.resize(picture, None, fx=SCREEN_SCALE, fy=SCREEN_SCALE, interpolation=cv2.INTER_AREA)
            self.timeline = [entry for entry in self.timeline if now - entry[0] < 2] + [(now, picture, small)]
        return now

    def _shown(self, when):
        """The timeline entry that was on screen at time `when`."""
        earlier = [entry for entry in self.timeline if entry[0] <= when]
        return earlier[-1] if earlier else self.timeline[0]

    def at(self, when, window=0.15):
        self._note()
        best = self._shown(when)
        others = [e[2] for e in self.timeline if abs(e[0] - when) <= window and e is not best and e[2].shape == best[2].shape]
        return best[2], others

    def latest(self):
        return self._note(), self.timeline[-1][2]

    # camera
    def read(self, newer_than=0, timeout=2.0):
        now = self._note()
        picture = self._shown(now - DELAY)[1]  # the projector is late
        if self.in_front is not None and self.pattern is None:
            picture = picture.copy()
            picture[self.in_front > 0] //= 12  # a shadow: almost no projector light
        view = cv2.warpPerspective(picture, VIEW, CAMERA, borderValue=(25, 25, 25))
        view = cv2.LUT(view, TONE).astype(np.float32) * np.float32([0.95, 1.0, 0.92])  # tone curve and colour cast
        view *= BANDS[self.frames % len(BANDS)]  # rainbow banding, different every frame
        view += NOISE[self.frames % len(NOISE)]
        self.frames += 1
        time.sleep(0.005)
        return np.clip(view, 0, 255).astype(np.uint8), now, self.frames

    def close(self):
        pass


def test_calibrate_then_find_a_fingertip():
    rig = SimulatedRig()
    engine = Engine(rig, camera=rig, screen=rig, landmarks=False)
    assert engine.calibrate(), engine.message
    assert "Calibrated" in engine.message
    assert abs(engine.latency - DELAY) < 0.08, f"measured delay {engine.latency:.2f} s"
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
    # Watch for two seconds: the fingertip must be found in the right place,
    # and holding still that long must give exactly one dwell click.
    engine.tracker.pointers.clear()
    seen, end = [], time.monotonic() + 2.0
    while time.monotonic() < end:
        seen.append(engine.step())
    pointers = seen[-1]
    assert len(pointers) == 1, pointers
    error = np.hypot(pointers[0]["x"] * W - tip[0], pointers[0]["y"] * H - tip[1])
    assert error < 0.015 * W, f"fingertip off by {error:.1f} px"
    downs = [p[0]["down"] for p in seen if p]
    presses = sum(1 for before, after in zip(downs, downs[1:]) if after and not before)
    assert presses == 1, f"expected one dwell click, saw {presses}"


def _arm(tip):
    """Mask of an arm reaching in from the bottom edge, fingertip at `tip` (content pixels)."""
    arm = np.zeros((H, W), np.uint8)
    cv2.line(arm, (int(tip[0] + 120), H + 20), (int(tip[0] + 14), int(tip[1] + 60)), 255, 60)
    cv2.line(arm, (int(tip[0] + 14), int(tip[1] + 60)), (int(tip[0]), int(tip[1] + 9)), 255, 18)
    return arm


def test_the_apps_own_feedback_does_not_disturb_the_pointer():
    """The stage draws a cursor ring at the pointer and, on the board, ink under
    a moving finger. Both change the picture exactly where the fingertip is; the
    pointer must stay on the fingertip all the same. (Both are drawn in bright
    colours: a finger is invisible to the camera over anything dark.)"""
    rig = SimulatedRig()
    engine = Engine(rig, camera=rig, screen=rig, landmarks=False)
    assert engine.calibrate(), engine.message
    board = np.full((H, W, 3), 255, np.uint8)
    rig.content = cv2.warpPerspective(board, engine.warp, (W, H))
    errors, last, start, frame = [], None, time.monotonic(), 0
    while (t := time.monotonic() - start) < 5:
        frame += 1
        tip = np.array([0.25 * W + 0.08 * W * t, 0.4 * H + 0.12 * H * np.sin(1.5 * t)])  # a wavy stroke
        rig.in_front = cv2.warpPerspective(_arm(tip), engine.warp, (W, H))
        pointers = engine.step()
        if not pointers:
            last = None
            continue
        at = (int(pointers[0]["x"] * W), int(pointers[0]["y"] * H))
        if t > 1:
            if last is not None:
                cv2.line(board, last, at, (255, 85, 51), 18, cv2.LINE_AA)  # blue ink follows the pointer
            last = at
            errors.append(np.hypot(at[0] - tip[0], at[1] - tip[1]))
        picture = board.copy()
        cv2.ellipse(picture, at, (30, 30), 0, -90, -90 + frame * 40 % 360, (60, 200, 255), -1)  # dwell fill, animating
        cv2.circle(picture, at, 30, (71, 99, 255), 8)  # the cursor ring
        rig.content = cv2.warpPerspective(picture, engine.warp, (W, H))
    assert len(errors) > 20, "the hand was lost"
    assert np.median(errors) < 0.015 * W, f"pointer off by {np.median(errors):.1f} px (median)"
    assert np.percentile(errors, 90) < 0.03 * W, f"pointer off by {np.percentile(errors, 90):.1f} px (90th percentile)"


def test_sprites_drifting_behind_a_still_hand_do_not_move_the_pointer():
    """A game: bright balloons rise through the picture, right behind the hand."""
    rig = SimulatedRig()
    engine = Engine(rig, camera=rig, screen=rig, landmarks=False)
    assert engine.calibrate(), engine.message
    tip = np.array([0.5 * W, 0.45 * H])
    rig.in_front = cv2.warpPerspective(_arm(tip), engine.warp, (W, H))
    colours = [(60, 90, 255), (60, 200, 250), (120, 200, 80), (255, 120, 60), (220, 90, 220)] * 2
    errors, lost, start = [], 0, time.monotonic()
    while (t := time.monotonic() - start) < 5:
        picture = np.full((H, W, 3), (235, 245, 255), np.uint8)
        for i, colour in enumerate(colours):
            centre = (int(W * (0.12 + 0.085 * i)), int(H + 150 - (t * 160 + i * 130) % (H + 300)))
            cv2.ellipse(picture, centre, (55, 70), 0, 0, 360, colour, -1, cv2.LINE_AA)
            cv2.ellipse(picture, centre, (55, 70), 0, 0, 360, tuple(int(v * 0.7) for v in colour), 5, cv2.LINE_AA)
        pointers = engine.step()
        if pointers and t > 1:
            errors.append(np.hypot(pointers[0]["x"] * W - tip[0], pointers[0]["y"] * H - tip[1]))
        lost += t > 1 and not pointers
        rig.content = cv2.warpPerspective(picture, engine.warp, (W, H))
    assert lost <= 2, f"the hand was lost in {lost} frames"
    assert np.percentile(errors, 90) < 0.03 * W, f"pointer off by {np.percentile(errors, 90):.1f} px (90th percentile)"


def test_a_hand_reaching_over_the_launcher_is_found_at_every_tile():
    """The launcher's tiles have thick dark outlines. Over them a hand cannot
    be seen, so an arm reaching for a tile is cut into pieces; they must still
    be read as one arm, with the fingertip on the tile."""
    launcher = cv2.imread(str(Path(__file__).parent.parent / "web" / "screenshots" / "01-launcher.png"))
    rig = SimulatedRig()
    engine = Engine(rig, camera=rig, screen=rig, landmarks=False)
    assert engine.calibrate(), engine.message
    rig.content = cv2.warpPerspective(cv2.resize(launcher, (W, H), interpolation=cv2.INTER_AREA), engine.warp, (W, H))
    tiles = [(0.26, 0.42), (0.62, 0.3), (0.86, 0.3), (0.62, 0.55), (0.86, 0.55), (0.14, 0.8), (0.38, 0.8), (0.62, 0.8), (0.86, 0.8)]
    missed = []
    for x, y in tiles:
        tip = np.array([x * W, y * H])
        rig.in_front = cv2.warpPerspective(_arm(tip), engine.warp, (W, H))
        engine.tracker.pointers.clear()
        errors, end = [], time.monotonic() + 0.8
        while time.monotonic() < end:
            pointers = engine.step()
            if pointers:
                errors.append(np.hypot(pointers[0]["x"] * W - tip[0], pointers[0]["y"] * H - tip[1]))
        if not errors or np.median(errors) > 0.02 * W:
            missed.append((x, y, round(float(np.median(errors))) if errors else None))
    assert not missed, f"fingertip not found at {missed}"


if __name__ == "__main__":
    test_calibrate_then_find_a_fingertip()
    test_a_hand_reaching_over_the_launcher_is_found_at_every_tile()
    test_the_apps_own_feedback_does_not_disturb_the_pointer()
    test_sprites_drifting_behind_a_still_hand_do_not_move_the_pointer()
    print("ok")
