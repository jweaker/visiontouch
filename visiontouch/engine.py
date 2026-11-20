"""The main loop: one camera frame in, pointers out.

    camera frame -> predicted background -> residual -> mask -> fingertips
                 -> hand pose -> tracker -> stage (or OS mouse)
"""
import base64
import json
import os
import queue
import re
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from .calibrate import colour_tiles, find_homography, marker_pattern
from .camera import Camera
from .hands import Landmarker, clean_mask, find_tips, pointing, read_pose
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
        self._next_try = 0.0  # earliest time for the next automatic calibration
        self.keystone, self.warp = True, np.eye(3)  # warp: content box pixels -> screen pixels
        self._frame_number, self._frame_time, self._count = 0, 0.0, 0
        self.source = None
        self.server.on_close = self.close
        self._open_camera(camera)

    # --- setup ---

    def _open_camera(self, source):
        """Switch to a camera. Raises RuntimeError, changing nothing, if it cannot be opened."""
        # `source` is normally a string for Camera; tests pass a ready-made camera object.
        name = getattr(source, "name", str(source))
        old = getattr(self, "camera", None)
        if old is not None and name == self.source:  # reopening the same device: it must be let go first
            old.close()
            old = None
        camera = source if hasattr(source, "read") else Camera(source)
        if old is not None:
            old.close()
        self.source, self.camera = name, camera
        self._frame_number, self.predictor = 0, None
        self._saved = STORE / f"calibration_{re.sub(r'[^A-Za-z0-9]', '_', name)}.npz"
        frame, _, _ = self.camera.read(timeout=10)
        try:  # a calibration saved earlier, if it is readable and fits this screen and camera
            data = np.load(self._saved)
            if frame is not None and tuple(data["screen"]) == self.screen.size and tuple(data["camera"]) == frame.shape[1::-1]:
                predictor = Predictor(data["H"], self.screen.size, frame.shape[1::-1])
                predictor.colour_map = data["colour_map"]
                self.latency, self.warp, self.predictor = float(data["latency"]), data["warp"], predictor
                self._send_warp()
        except (OSError, KeyError, ValueError):
            pass

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
        for _ in range(2):
            frame, _, number = self.camera.read(newer_than=self._frame_number)
            if frame is None:
                raise RuntimeError("the camera stopped sending pictures")
            self._frame_number = number
        return frame

    def calibrate(self):
        """Project the calibration patterns and build the predictor. About 10
        seconds. Returns True on success; on failure the reason is in `message`."""
        if self.mode != "apps":
            return self._say("Calibration failed: switch to Apps first, the picture must fill the screen")
        try:
            return self._calibrate()
        except (RuntimeError, ValueError, np.linalg.LinAlgError) as problem:
            return self._say(f"Calibration failed: {problem}")
        finally:
            self.server.show(None)  # never leave a pattern on the wall

    def _calibrate(self):
        w, h = self.screen.size
        pattern, corners = marker_pattern(w, h)
        self._say("Calibrating: finding the screen")
        if not self.server.show(pattern):
            return self._say("Calibration failed: the stage window is not connected")
        best, frame = None, self._fresh_frame(1.2)
        for _ in range(4):  # the sharpest of a few frames
            H, error, count = find_homography(frame, corners)
            if H is not None and count >= 12 and (best is None or error < best[1]):
                best = (H, error, count)
            frame = self._fresh_frame(0)
        if best is None or best[1] > 6:
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
        self.predictor = predictor
        STORE.mkdir(parents=True, exist_ok=True)
        np.savez(self._saved, H=best[0], colour_map=predictor.colour_map, latency=self.latency,
                 screen=self.screen.size, camera=frame.shape[1::-1], warp=self.warp)
        if self._recording:  # a recording needs the calibration it was made with
            (self._recording[0] / self._saved.name).write_bytes(self._saved.read_bytes())
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
        # Files are written by a helper thread, so that recording does not slow the engine down.
        self._writes = queue.Queue()
        threading.Thread(target=lambda: [cv2.imwrite(*job) for job in iter(self._writes.get, None)], daemon=True).start()

    def _record(self, frame, when, screen):
        folder, frames = self._recording
        if not frames or frames[-1]["screen_id"] != id(screen):  # the screen changed: store it once
            self._writes.put((str(folder / f"screen_{len(frames):06d}.png"), screen, [cv2.IMWRITE_PNG_COMPRESSION, 1]))
            name = f"screen_{len(frames):06d}.png"
        else:
            name = frames[-1]["screen"]
        self._writes.put((str(folder / f"frame_{len(frames):06d}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 92]))
        frames.append({"time": when, "screen": name, "screen_id": id(screen)})
        if len(frames) % 30 == 0:
            (folder / "index.json").write_text(json.dumps({"camera": self.source, "screen_size": self.screen.size, "frames": frames}))

    # --- per frame ---

    def step(self):
        frame, when, number = self.camera.read(newer_than=self._frame_number, timeout=1.0)
        if frame is not None:
            self._last_frame, self._frame_number, self._frame_time = time.monotonic(), number, when
        if frame is None or self.predictor is None:
            self._drive_mouse([])  # nothing seen: never keep the mouse button held
            time.sleep(0.02)
            return None
        screen, others = self.screen.at(when - self.latency)
        if screen is None:
            return None
        if self._recording:
            self._record(frame, when, screen)
        p = self.predictor
        residual, predicted, observed = p.residual(screen, frame, others or (), self.blind)
        mask, labels, blobs = clean_mask(residual, self.sensitivity)
        # If most of the picture disagrees with the prediction for seconds on
        # end, it is not a hand: the camera or the projector has moved.
        if mask.sum() < 0.6 * p.inside.sum():
            self._covered_since = when
        # A small knock shows up as a sideways shift between the predicted and
        # the observed picture; phase correlation measures it (once a second).
        if self._count % 30 == 0 and not others:  # only while the screen is still
            grey = [cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) for image in (predicted, observed)]
            (dx, dy), confidence = cv2.phaseCorrelate(grey[0], grey[1], cv2.createHanningWindow(p.size, cv2.CV_32F))
            self._drift = self._drift + 1 if confidence > 0.25 and np.hypot(dx, dy) > 2.5 else 0

        if self.landmarker:
            detections, drawn = self._find_hands(frame, mask)
        else:
            tips, drawn = [_apply(p.work_to_cam, hand["tip"]) for hand in find_tips(labels, blobs, p.inside)], []
            detections = [{"pos": self._to_content(_apply(p.cam_to_screen, tip)), "pose": None} for tip in tips]
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

    def _find_hands(self, frame, mask):
        """Detections for the tracker, and the landmarks seen (for the debug view).

        The hand model looks closely where each known hand was a moment ago,
        and takes turns searching the left and the right half of the picture
        for new ones (all the time while no hand is known, now and then
        otherwise). The pointer is the index fingertip. The model misses a
        small, far hand in about one frame out of four; while the mask still
        shows a pointing hand there, the pointer stays where it was."""
        p = self.predictor
        to_work, width = np.linalg.inv(p.work_to_cam), mask.shape[1]
        can_point = lambda spot: pointing(mask, spot, 0.02 * width, 0.3 * width)
        known = [_apply(p.screen_to_work, self._to_screen({"x": x, "y": y})) for x, y in (t.filter.state[:2] for t in self.tracker.pointers)]
        looks = [(_apply(p.work_to_cam, centre), 0.13 * p.span) for centre in known]
        turn, half_width = self._count % (6 if known else 2), width // 2
        if turn < 2 and mask[:, turn * half_width:(turn + 1) * half_width].any():  # nothing in front of the picture: nothing to search
            looks.append((_apply(p.work_to_cam, ((turn + 0.5) * half_width, mask.shape[0] / 2)), 0.28 * p.span))
        seen = [points for look in looks for points in self.landmarker.detect(frame, *look)]
        spots = [(_apply(to_work, points[8]), points) for points in seen] + [(centre, None) for centre in known]  # hands the model saw come first
        found = []
        for spot, points in spots:
            if can_point(spot) and all(np.linalg.norm(spot - other) > 0.08 * width for other, _ in found):
                found.append((spot, points))
        detections = [{"pos": self._to_content(_apply(p.cam_to_screen @ p.work_to_cam, spot)), "pose": read_pose(points) if points is not None else None,
                       "hand": points is not None} for spot, points in found]
        return detections, [points for _, points in found if points is not None]

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
        """Move the OS mouse with the first hand (desktop mode). Called with no
        pointers it only lets go of the button, which is safe in any mode."""
        if self.mouse is None:
            if not pointers:
                return
            import pyautogui

            pyautogui.PAUSE, pyautogui.FAILSAFE = 0, False
            self.mouse, self._mouse_down, self._mouse_hand = pyautogui, False, None
        first = pointers[0] if pointers else None
        # Let go when the hand is gone, and before another hand takes over the mouse.
        if self._mouse_down and (first is None or first["id"] != self._mouse_hand or not first["down"]):
            self.mouse.mouseUp()
            self._mouse_down = False
        if first is None:
            return
        x, y = self._to_screen(first)
        self.mouse.moveTo(self.screen.origin[0] + x, self.screen.origin[1] + y)
        if first["down"] and not self._mouse_down:
            self.mouse.mouseDown()
            self._mouse_down, self._mouse_hand = True, first["id"]

    def close(self):
        """Called when the window closes: let go of the mouse and the camera."""
        self._drive_mouse([])
        self.camera.close()

    def _set_mode(self, mode):
        """apps: the stage is fullscreen and receives the pointers. desktop: the
        stage shrinks to a small strip that stays on top (it holds the button
        to come back) and the pointers drive the OS mouse."""
        self._drive_mouse([])
        self.mode = mode
        view = getattr(self.server, "view", None)  # the built-in window, absent in browser mode
        if view is not None:
            view.on_top = False
            before = self.server.window
            view.toggle_fullscreen()
            # The fullscreen animation must finish before the window can be resized;
            # the stage reports its new size when it has (slow on a busy machine).
            end = time.monotonic() + 6
            while time.monotonic() < end and self.server.window == before:
                time.sleep(0.1)
            time.sleep(0.7)
            if mode == "desktop":
                for _ in range(10):  # a resize asked for too early is ignored: check, and ask again
                    view.resize(*STRIP)
                    time.sleep(1.0)
                    if self.server.window and self.server.window[0] < 2 * STRIP[0]:
                        break
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
            if self.mode == "apps" and self.server.window and now - self._last_frame < 1 and now > self._next_try:
                moved = self.predictor is not None and (self._drift >= 3 or self._frame_time - self._covered_since > 4)
                if moved:
                    self._say("The camera or projector has moved: recalibrating")
                if moved or self.predictor is None:
                    self.calibrate()
                    self._drift, self._covered_since = 0, self._frame_time
                    self._next_try = time.monotonic() + 20  # if that failed, do not flash patterns in a loop
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
