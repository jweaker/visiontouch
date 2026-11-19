"""The main loop: one camera frame in, pointers out.

    camera frame -> predicted background -> residual -> mask -> fingertips
                 -> hand pose -> tracker -> stage (or OS mouse)
"""
import json
import re
import time
from pathlib import Path

import cv2
import numpy as np

from .calibrate import colour_tiles, find_homography, marker_pattern
from .camera import Camera
from .hands import Landmarker, clean_mask, find_tips, read_pose
from .predict import SCREEN_SCALE, Predictor
from .screen import Screen
from .track import Tracker

STORE = Path.home() / ".visiontouch"
MASK_GRID = (64, 36)


def _apply(matrix, point):
    """Apply a 3x3 homography to one (x, y) point."""
    x, y, w = matrix @ [point[0], point[1], 1.0]
    return np.array([x / w, y / w])


class Engine:
    def __init__(self, server, camera="0", screen=None, landmarks=True):
        self.server = server
        self.screen = screen or Screen()
        self.tracker = Tracker()
        self.landmarker = Landmarker() if landmarks else None
        self.mode, self.mask_wanted, self.message = "apps", False, ""
        self.fps, self.latency, self.predictor = 0.0, 0.2, None
        self.mouse = None
        self._frame_number, self._count = 0, 0
        self._open_camera(camera)

    # --- setup ---

    def _open_camera(self, source):
        if getattr(self, "camera", None):
            self.camera.close()
        self.source = str(source)
        self.camera = Camera(source)
        self._frame_number, self.predictor = 0, None
        saved = STORE / f"calibration_{re.sub(r'[^A-Za-z0-9]', '_', self.source)}.npz"
        self._saved = saved
        frame, _, _ = self.camera.read(timeout=10)
        if saved.exists() and frame is not None:
            data = np.load(saved)
            if tuple(data["screen"]) == self.screen.size and tuple(data["camera"]) == frame.shape[1::-1]:
                self.predictor = Predictor(data["H"], self.screen.size, frame.shape[1::-1])
                self.predictor.colour_map = data["colour_map"]
                self.latency = float(data["latency"])

    def _say(self, message):
        self.message = message
        self._send_state()
        return False

    def _send_state(self):
        self.server.send({"t": "state", "calibrated": self.predictor is not None, "camera": self.source,
                          "fps": round(self.fps, 1), "latency_ms": round(self.latency * 1000), "mode": self.mode,
                          "message": self.message})

    def _fresh_frame(self, wait):
        """A camera frame taken after waiting `wait` seconds (lets a new pattern arrive)."""
        time.sleep(wait)
        frame, _, self._frame_number = self.camera.read(newer_than=self._frame_number)
        frame, _, self._frame_number = self.camera.read(newer_than=self._frame_number)
        return frame

    def calibrate(self):
        """Project the calibration patterns and build the predictor. About 5 seconds."""
        w, h = self.screen.size
        pattern, corners = marker_pattern(w, h)
        self._say("Calibrating: finding the screen")
        if not self.server.show(pattern):
            return self._say("Calibration failed: the stage window is not connected")
        best, frame = None, self._fresh_frame(1.2)
        for _ in range(4):  # the sharpest of a few frames
            H, error, count = find_homography(frame, corners)
            if H is not None and (best is None or error < best[1]):
                best = (H, error, count)
            frame = self._fresh_frame(0)
        if best is None or best[2] < 12 or best[1] > 6:
            self.server.show(None)
            return self._say("Calibration failed: the camera must see the whole projected picture")
        predictor = Predictor(best[0], (w, h), frame.shape[1::-1])
        self._say("Calibrating: learning colours")
        pairs = []
        for seed in range(4):
            tiles = colour_tiles(w, h, seed)
            self.server.show(tiles)
            small = cv2.resize(tiles, None, fx=SCREEN_SCALE, fy=SCREEN_SCALE, interpolation=cv2.INTER_AREA)
            pairs.append((small, self._fresh_frame(0.9 if seed == 0 else 0.6)))
        predictor.calibrate_colour(pairs)
        self.latency = self._measure_latency(predictor)
        self.server.show(None)
        self.predictor = predictor
        STORE.mkdir(exist_ok=True)
        np.savez(self._saved, H=best[0], colour_map=predictor.colour_map, latency=self.latency,
                 screen=self.screen.size, camera=frame.shape[1::-1])
        self._say(f"Calibrated: {best[2]} markers, {best[1]:.1f} px error, {self.latency * 1000:.0f} ms delay")
        return True

    def _measure_latency(self, predictor):
        """Delay between a change appearing in our screenshots and in the camera:
        flash black then white and time both."""
        w, h = self.screen.size
        self.server.show(np.zeros((h, w, 3), np.uint8))
        time.sleep(0.8)
        dark = predictor.crop_camera(self.camera.read()[0])[predictor.inside].mean()
        self.server.show(np.full((h, w, 3), 255, np.uint8))
        seen_screen = seen_camera = None
        end = time.monotonic() + 1.5
        while time.monotonic() < end and not (seen_screen and seen_camera):
            when, shot = self.screen.latest()
            if seen_screen is None and shot is not None and shot.mean() > 128:
                seen_screen = when
            frame, when, self._frame_number = self.camera.read(newer_than=self._frame_number, timeout=0.01)
            if seen_camera is None and frame is not None and predictor.crop_camera(frame)[predictor.inside].mean() > dark + 40:
                seen_camera = when
        if seen_screen is None or seen_camera is None:
            return 0.2
        return float(np.clip(seen_camera - seen_screen, 0.03, 0.6))

    # --- per frame ---

    def step(self):
        frame, when, number = self.camera.read(newer_than=self._frame_number, timeout=1.0)
        if frame is None or self.predictor is None:
            time.sleep(0.02)
            return None
        self._frame_number = number
        screen, changed = self.screen.at(when - self.latency)
        if screen is None:
            return None
        p = self.predictor
        ignore = None
        if changed is not None:  # parts of the screen in motion cannot be compared
            ignore = cv2.dilate(p.warp_screen(changed.astype(np.uint8)), np.ones((5, 5), np.uint8)) > 0
        residual, predicted, observed = p.residual(screen, frame, ignore)
        mask, labels, blobs = clean_mask(residual)

        detections, drawn = [], []
        for hand in find_tips(labels, blobs, p.inside):
            tip = _apply(p.work_to_cam, hand["tip"])
            pose, position = None, tip
            if self.landmarker:
                towards_arm = _apply(p.work_to_cam, hand["entry"]) - tip
                half = 0.13 * p.span
                centre = tip + towards_arm / (np.linalg.norm(towards_arm) + 1e-6) * half * 0.5
                points = self.landmarker.detect(frame, centre, half)
                if points is not None:
                    pose, position = read_pose(points)
                    drawn.append(points)
            x, y = _apply(p.cam_to_screen, position) / self.screen.size
            detections.append({"pos": (x, y), "pose": pose})
        pointers, gestures = self.tracker.update(detections, when)

        self.server.send({"t": "pointers", "p": pointers})
        for name in gestures:
            self.server.send({"t": "gesture", "name": name})
        if self.mode == "desktop":
            self._drive_mouse(pointers)
        self._count += 1
        if self.mask_wanted and self._count % 2 == 0:
            to_grid = np.diag([MASK_GRID[0] / self.screen.size[0], MASK_GRID[1] / self.screen.size[1], 1.0]) @ np.linalg.inv(p.screen_to_work)
            grid = cv2.warpPerspective(mask.astype(np.uint8) * 255, to_grid, MASK_GRID, flags=cv2.INTER_AREA)
            self.server.send({"t": "mask", "w": MASK_GRID[0], "h": MASK_GRID[1], "b64": __import__("base64").b64encode(np.where(grid > 60, 255, 0).astype(np.uint8).tobytes()).decode()})
        if self._count % 3 == 0:
            self._publish_debug(p, frame, observed, predicted, residual, mask, pointers, drawn)
        return pointers

    def _publish_debug(self, p, frame, observed, predicted, residual, mask, pointers, landmarks):
        view = observed.clip(0, 255).astype(np.uint8)
        self.server.debug("camera", view)
        to_screen = np.diag([0.25, 0.25, 1.0]) @ np.linalg.inv(p.screen_to_work)
        size = (self.screen.size[0] // 4, self.screen.size[1] // 4)
        self.server.debug("rectified", cv2.warpPerspective(view, to_screen, size))
        self.server.debug("predicted", predicted.clip(0, 255).astype(np.uint8))
        self.server.debug("residual", cv2.applyColorMap(np.clip(residual * 8, 0, 255).astype(np.uint8), cv2.COLORMAP_JET))
        self.server.debug("mask", mask.astype(np.uint8) * 255)
        overlay = view.copy()
        overlay[mask] = overlay[mask] // 2 + np.array([0, 110, 0], np.uint8)
        cam_to_work = np.linalg.inv(p.work_to_cam)
        for points in landmarks:
            for point in points:
                cv2.circle(overlay, tuple(_apply(cam_to_work, point).astype(int)), 2, (255, 200, 0), -1)
        for pointer in pointers:
            centre = _apply(p.screen_to_work, (pointer["x"] * self.screen.size[0], pointer["y"] * self.screen.size[1])).astype(int)
            cv2.circle(overlay, tuple(centre), 9, (0, 0, 255) if pointer["down"] else (0, 255, 255), 2)
        self.server.debug("overlay", overlay)

    def _drive_mouse(self, pointers):
        if self.mouse is None:
            import pyautogui

            pyautogui.PAUSE, pyautogui.FAILSAFE = 0, False
            self.mouse, self._mouse_down = pyautogui, False
        if not pointers:
            if self._mouse_down:
                self.mouse.mouseUp()
                self._mouse_down = False
            return
        first = pointers[0]
        self.mouse.moveTo(self.screen.origin[0] + first["x"] * self.screen.size[0],
                          self.screen.origin[1] + first["y"] * self.screen.size[1])
        if first["down"] != self._mouse_down:
            (self.mouse.mouseDown if first["down"] else self.mouse.mouseUp)()
            self._mouse_down = first["down"]

    def _handle(self, m):
        if m.get("t") == "log":
            STORE.mkdir(exist_ok=True)
            with open(STORE / "log.jsonl", "a") as out:
                out.write(json.dumps({"time": time.time(), **m}) + "\n")
        elif m.get("t") == "hello":
            self._send_state()
        elif m.get("t") == "cmd":
            name, value = m.get("name"), m.get("value")
            if name == "calibrate":
                self.calibrate()
            elif name == "mode" and value in ("apps", "desktop"):
                self.mode = value
            elif name == "subscribe_mask":
                self.mask_wanted = bool(value)
            elif name == "camera":
                try:
                    self._open_camera(value)
                except RuntimeError as error:
                    self._say(str(error))
            self._send_state()

    def run(self):
        last_state = started = time.monotonic()
        frames = 0
        while True:
            while not self.server.inbox.empty():
                self._handle(self.server.inbox.get())
            if self.step() is not None:
                frames += 1
            now = time.monotonic()
            if now - last_state > 1:
                self.fps, frames, last_state = frames / (now - last_state), 0, now
                self._send_state()
