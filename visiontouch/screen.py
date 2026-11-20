"""Screen capture. The engine has to know what was on the screen at the moment
a camera frame was taken, which is a little in the past (projector and camera
both add delay), so a thread keeps a short history of half-size screenshots."""
import threading
import time
from collections import deque

import cv2
import mss
import numpy as np

from .predict import SCREEN_SCALE


class Screen:
    def __init__(self, monitor=1, history=1.0):
        self._history = history
        self._frames = deque()  # (time, half-size BGR picture), oldest first
        self._lock = threading.Lock()
        with mss.MSS() as grabber:
            box = grabber.monitors[monitor]
        self.monitor = monitor
        self.size = (box["width"], box["height"])
        self.origin = (box["left"], box["top"])
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        with mss.MSS() as grabber:
            box = grabber.monitors[self.monitor]
            while self._running:
                try:
                    shot = np.asarray(grabber.grab(box))[..., :3]
                except Exception:  # a failed grab (display asleep, permission dialog): try again
                    time.sleep(0.2)
                    continue
                now = time.monotonic()
                small = cv2.resize(shot, None, fx=SCREEN_SCALE, fy=SCREEN_SCALE, interpolation=cv2.INTER_AREA)
                with self._lock:
                    # An unchanged screen keeps the same array object, which lets
                    # the predictor reuse its work for it.
                    if self._frames and np.array_equal(self._frames[-1][1], small):
                        small = self._frames[-1][1]
                    self._frames.append((now, small))
                    while now - self._frames[0][0] > self._history:
                        self._frames.popleft()

    def latest(self):
        """(time, picture) of the newest screenshot."""
        with self._lock:
            return self._frames[-1] if self._frames else (0.0, None)

    def at(self, when, window=0.15):
        """The screen picture at time `when`, plus the other pictures shown
        within `window` seconds around it. The camera's delay varies by a few
        frames, so while the screen is changing it may have seen any of them."""
        with self._lock:
            frames = list(self._frames)
        if not frames:
            return None, []
        frames.sort(key=lambda f: abs(f[0] - when))
        best = frames[0][1]
        others = {id(f[1]): f[1] for f in frames[1:] if abs(f[0] - when) <= window and f[1] is not best}
        return best, list(others.values())

    def close(self):
        self._running = False
