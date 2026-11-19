"""The main loop: one camera frame in, pointers out.

    camera frame -> predicted background -> residual -> mask -> fingertips
                 -> hand pose -> tracker -> stage (or OS mouse)
"""
import base64
import json
import os
import re
import time
from pathlib import Path

import cv2
import numpy as np

from .calibrate import colour_tiles, find_homography, marker_pattern
from .camera import Camera
from .hands import Landmarker, clean_mask, find_tips, read_pose
from .keystone import correction, find_frame
from .predict import Predictor
from .screen import Screen
from .track import Tracker

STORE = Path(os.environ.get("VISIONTOUCH_HOME", Path.home() / ".visiontouch"))  # calibration and logs
MASK_GRID = (64, 36)
STRIP = (420, 110)  # size of the stage window in desktop mode


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
        self._recording = None  # (folder, list of frame records) while a session is being recorded
        self.blind = None  # working-image mask of places to disregard (set by rig tests)
        self.sensitivity = 1.0  # user knob: scales the detection thresholds
        self._covered_since = self._last_frame = time.monotonic()
        self._drift = 0  # consecutive checks in which the picture looked shifted
        self.keystone, self.warp = True, np.eye(3)  # warp: content box pixels -> screen pixels
        self._frame_number, self._frame_time, self._count = 0, 0.0, 0
        self._open_camera(camera)

    # --- setup ---

    def _open_camera(self, source):
        if getattr(self, "camera", None):
            self.camera.close()
        # `source` is normally a string for Camera; tests pass a ready-made camera object.
        self.source = getattr(source, "name", str(source))
        self.camera = source if hasattr(source, "read") else Camera(source)
        self._frame_number, self.predictor = 0, None
        saved = STORE / f"calibration_{re.sub(r'[^A-Za-z0-9]', '_', self.source)}.npz"
        self._saved = saved
        frame, _, _ = self.camera.read(timeout=10)
        if saved.exists() and frame is not None:
            data = np.load(saved)
            if "warp" in data and tuple(data["screen"]) == self.screen.size and tuple(data["camera"]) == frame.shape[1::-1]:
                self.predictor = Predictor(data["H"], self.screen.size, frame.shape[1::-1])
                self.predictor.colour_map = data["colour_map"]
                self.latency, self.warp = float(data["latency"]), data["warp"]
                self._send_warp()

    def _say(self, message):
        self.message = message
        self._send_state()
        return False

    def _send_state(self):
        self.server.send({"t": "state", "calibrated": self.predictor is not None, "camera": self.source,
                          "fps": round(self.fps, 1), "latency_ms": round(self.latency * 1000), "mode": self.mode,
                          "keystone": self.keystone, "sensitivity": self.sensitivity,
                          "dwell": "hold" if self.tracker.hold else "tap", "message": self.message})

    def _content(self):
        """Content box pixels -> screen pixels: the keystone correction while
        the stage is fullscreen, nothing in desktop mode or when switched off."""
        return self.warp if self.keystone and self.mode == "apps" else np.eye(3)

    def _send_warp(self):
        """Tell the stage how to pre-distort its content box (keystone correction)."""
        if self.predictor is not None:
            self.predictor.set_area(self._content())
        if self.predictor is None or not self.server.window or np.allclose(self._content(), np.eye(3)):
            return self.server.send({"t": "warp", "m": None})
        # The matrix is in screen pixels; the stage works in window (CSS) pixels.
        scale = np.diag([self.server.window[0] / self.screen.size[0], self.server.window[1] / self.screen.size[1], 1.0])
        self.server.send({"t": "warp", "m": (scale @ self.warp @ np.linalg.inv(scale)).ravel().tolist()})

    def _to_content(self, screen_point):
        """Screen pixels -> position in the content box, 0..1."""
        return _apply(np.linalg.inv(self._content()), screen_point) / self.screen.size

    def _to_screen(self, pointer):
        """A pointer (content box, 0..1) -> screen pixels."""
        point = (pointer["x"] * self.screen.size[0], pointer["y"] * self.screen.size[1])
        return _apply(self._content(), point)

    def _fresh_frame(self, wait):
        """A camera frame taken after waiting `wait` seconds (lets a new pattern arrive)."""
        time.sleep(wait)
        frame, _, self._frame_number = self.camera.read(newer_than=self._frame_number)
        frame, _, self._frame_number = self.camera.read(newer_than=self._frame_number)
        return frame

    def calibrate(self):
        """Project the calibration patterns and build the predictor. About 10 seconds."""
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
            self.server.show(colour_tiles(w, h, seed))
            frame = self._fresh_frame(0.9 if seed == 0 else 0.6)
            # Pair the photo with a screenshot rather than with the pattern itself:
            # a notification or dialog on top of the pattern is then accounted for.
            pairs.append((self.screen.latest()[1], frame))
        predictor.calibrate_colour(pairs)
        self.latency = self._measure_latency(predictor)  # leaves a white screen up
        # Keystone: look for the projection screen's frame around the white picture.
        quad = cv2.perspectiveTransform(np.float32([[[0, 0], [w, 0], [w, h], [0, h]]]), np.linalg.inv(best[0]))[0]
        screen_frame = find_frame(self._fresh_frame(0.5), quad)
        self.warp = correction(best[0], (w, h), frame.shape[1::-1], screen_frame)
        self.server.show(None)
        self.predictor = predictor
        STORE.mkdir(parents=True, exist_ok=True)
        np.savez(self._saved, H=best[0], colour_map=predictor.colour_map, latency=self.latency,
                 screen=self.screen.size, camera=frame.shape[1::-1], warp=self.warp)
        self._send_warp()
        straight = "squared to the screen frame" if screen_frame is not None else "squared to the camera's view"
        self._say(f"Calibrated: {best[2]} markers, {best[1]:.1f} px error, {self.latency * 1000:.0f} ms delay, {straight}")
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

    def record(self, folder):
        """Save every camera frame and screen picture from now on, so the
        session can be replayed offline (python -m eval.replay <folder>)."""
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        if self._saved.exists():
            (folder / self._saved.name).write_bytes(self._saved.read_bytes())
        self._recording = (folder, [])

    def _record(self, frame, when, screen):
        folder, frames = self._recording
        if not frames or frames[-1]["screen_id"] != id(screen):  # the screen changed: store it once
            cv2.imwrite(str(folder / f"screen_{len(frames):06d}.png"), screen)
            name = f"screen_{len(frames):06d}.png"
        else:
            name = frames[-1]["screen"]
        cv2.imwrite(str(folder / f"frame_{len(frames):06d}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        frames.append({"time": when, "screen": name, "screen_id": id(screen)})
        if len(frames) % 30 == 0:
            (folder / "index.json").write_text(json.dumps({"camera": self.source, "screen_size": self.screen.size, "frames": frames}))

    # --- per frame ---

    def step(self):
        frame, when, number = self.camera.read(newer_than=self._frame_number, timeout=1.0)
        if frame is not None:
            self._last_frame = time.monotonic()
        if frame is None or self.predictor is None:
            time.sleep(0.02)
            return None
        self._frame_number, self._frame_time = number, when
        screen, changed = self.screen.at(when - self.latency)
        if screen is None:
            return None
        if self._recording:
            self._record(frame, when, screen)
        p = self.predictor
        ignore = None
        if changed is not None:  # parts of the screen in motion cannot be compared
            ignore = cv2.dilate(p.warp_screen(changed.astype(np.uint8)), np.ones((5, 5), np.uint8)) > 0
        if self.blind is not None:
            ignore = self.blind if ignore is None else ignore | self.blind
        residual, predicted, observed = p.residual(screen, frame, ignore)
        mask, labels, blobs = clean_mask(residual, self.sensitivity)
        # If most of the picture disagrees with the prediction for seconds on
        # end, it is not a hand: the camera or the projector has moved.
        if mask.sum() < 0.6 * p.inside.sum():
            self._covered_since = when
        # A small knock shows up as a sideways shift between the predicted and
        # the observed picture; phase correlation measures it (once a second).
        if self._count % 30 == 0:
            grey = [cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) for image in (predicted, observed)]
            (dx, dy), confidence = cv2.phaseCorrelate(grey[0], grey[1], cv2.createHanningWindow(p.size, cv2.CV_32F))
            self._drift = self._drift + 1 if confidence > 0.25 and np.hypot(dx, dy) > 2.5 else 0

        detections, drawn = [], []
        for hand in find_tips(labels, blobs, p.inside):
            tip = _apply(p.work_to_cam, hand["tip"])
            pose, position = None, tip
            if self.landmarker:
                towards_arm = _apply(p.work_to_cam, hand["entry"]) - tip
                half = 0.13 * p.span
                centre = tip + towards_arm / (np.linalg.norm(towards_arm) + 1e-6) * half * 0.5
                points = self.landmarker.detect(frame, centre, half)
                # Believe the landmarks only if the hand they describe ends where
                # the blob ends; otherwise they were imagined on the background.
                if points is not None and np.linalg.norm(points - tip, axis=1).min() < 0.3 * half:
                    pose, position = read_pose(points)
                    drawn.append(points)
            detections.append({"pos": self._to_content(_apply(p.cam_to_screen, position)), "pose": pose})
        pointers, gestures = self.tracker.update(detections, when)

        self.server.send({"t": "pointers", "p": pointers})
        for name in gestures:
            self.server.send({"t": "gesture", "name": name})
        if self.mode == "desktop":
            self._drive_mouse(pointers)
        self._count += 1
        if self.mask_wanted and self._count % 2 == 0:
            to_grid = np.diag([MASK_GRID[0] / self.screen.size[0], MASK_GRID[1] / self.screen.size[1], 1.0]) @ np.linalg.inv(self._content()) @ np.linalg.inv(p.screen_to_work)
            grid = cv2.warpPerspective(mask.astype(np.uint8) * 255, to_grid, MASK_GRID, flags=cv2.INTER_AREA)
            self.server.send({"t": "mask", "w": MASK_GRID[0], "h": MASK_GRID[1], "b64": base64.b64encode(np.where(grid > 60, 255, 0).astype(np.uint8).tobytes()).decode()})
        if self._count % 3 == 0 and getattr(self.server, "viewers", 1):  # only while someone is watching
            self._publish_debug(p, observed, predicted, residual, mask, pointers, drawn)
        return pointers

    def _publish_debug(self, p, observed, predicted, residual, mask, pointers, landmarks):
        view = observed.clip(0, 255).astype(np.uint8)
        self.server.debug("camera", view)
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
            centre = _apply(p.screen_to_work, self._to_screen(pointer)).astype(int)
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
        x, y = self._to_screen(first)
        self.mouse.moveTo(self.screen.origin[0] + x, self.screen.origin[1] + y)
        if first["down"] != self._mouse_down:
            (self.mouse.mouseDown if first["down"] else self.mouse.mouseUp)()
            self._mouse_down = first["down"]

    def _set_mode(self, mode):
        """apps: the stage is fullscreen and receives the pointers. desktop: the
        stage shrinks to a small strip that stays on top (it holds the button
        to come back) and the pointers drive the OS mouse."""
        self.mode = mode
        view = getattr(self.server, "view", None)  # the built-in window, absent in browser mode
        if view is not None:
            view.on_top = False
            view.toggle_fullscreen()
            time.sleep(2.0)  # the fullscreen animation must finish before the window can be resized
            if mode == "desktop":
                view.resize(*STRIP)
                time.sleep(0.5)
                view.move(self.screen.origin[0] + (self.screen.size[0] - STRIP[0]) // 2, self.screen.origin[1] + 40)
                view.on_top = True
        self._send_warp()

    def _handle(self, m):
        if m.get("t") == "log":
            STORE.mkdir(parents=True, exist_ok=True)
            with open(STORE / "log.jsonl", "a") as out:
                out.write(json.dumps({"time": time.time(), **m}) + "\n")
        elif m.get("t") == "hello":
            self._send_warp()
            self._send_state()
        elif m.get("t") == "cmd":
            name, value = m.get("name"), m.get("value")
            if name == "calibrate":
                self.calibrate()
            elif name == "mode" and value in ("apps", "desktop") and value != self.mode:
                self._set_mode(value)
            elif name == "subscribe_mask":
                self.mask_wanted = bool(value)
            elif name == "keystone":
                self.keystone = bool(value)
                self._send_warp()
            elif name == "dwell":
                self.tracker.hold = value == "hold"
            elif name == "sensitivity":
                self.sensitivity = float(np.clip(float(value), 0.4, 2.5))
            elif name == "camera":
                try:
                    self._open_camera(value)
                except RuntimeError as error:
                    self._say(str(error))
            self._send_state()

    def run(self):
        last_state = time.monotonic()
        frames = 0
        while True:
            while not self.server.inbox.empty():
                self._handle(self.server.inbox.get())
            now = time.monotonic()
            frames += self.step() is not None
            # Look after itself: calibrate on first use, recalibrate after a bump,
            # reopen a camera that stopped sending pictures.
            if self.mode == "apps" and self.server.window and now - self._last_frame < 1:
                if self.predictor is None and not self.message.startswith("Calibration failed"):
                    self.calibrate()
                elif self.predictor is not None and (self._drift >= 3 or self._frame_time - self._covered_since > 4):
                    self._say("The camera or projector has moved: recalibrating")
                    self.calibrate()
                    self._drift, self._covered_since = 0, self._frame_time
            if now - self._last_frame > 4:
                self._say("The camera stopped sending pictures: reconnecting")
                try:
                    self._open_camera(self.source)
                except RuntimeError:
                    time.sleep(2)
                self._last_frame = time.monotonic()
            if now - last_state > 1:
                self.fps, frames, last_state = frames / (now - last_state), 0, now
                self._send_state()
