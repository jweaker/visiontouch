"""Replays a recorded session through the engine, offline.

    VISIONTOUCH_RECORD=runs/hand1 python -m visiontouch    (record: use the app, then quit)
    python -m eval.replay runs/hand1 [--video]             (replay as often as needed)

Prints what the engine reports for every frame, and with --video writes
overlay.mp4 (camera view with mask, landmarks and pointers drawn in).
Changing the code and replaying again is how thresholds get tuned on real hands.
"""
import json
import os
import queue
import sys
from pathlib import Path

import cv2
import numpy as np

FOLDER = Path(sys.argv[1])
os.environ["VISIONTOUCH_HOME"] = str(FOLDER)  # use the calibration saved with the recording

from visiontouch.engine import Engine  # noqa: E402


class Recording:
    """Plays the roles of camera, screen and stage server from files."""

    def __init__(self, folder):
        index = json.loads((folder / "index.json").read_text())
        self.folder, self.frames, self.name = folder, index["frames"], index["camera"]
        self.size, self.origin, self.window = tuple(index["screen_size"]), (0, 0), tuple(index["screen_size"])
        self.inbox, self.position, self.sent, self.images = queue.Queue(), -1, [], {}
        self._screens = {}

    def read(self, newer_than=0, timeout=2.0):
        self.position += 1
        if self.position >= len(self.frames):
            return None, 0.0, 0
        frame = cv2.imread(str(self.folder / f"frame_{self.position:06d}.jpg"))
        return frame, self.frames[self.position]["time"], self.position + 1

    def at(self, when, window=0.12):
        name = self.frames[max(self.position, 0)]["screen"]
        if name not in self._screens:
            self._screens[name] = cv2.imread(str(self.folder / name))
        return self._screens[name], None

    def send(self, message):
        self.sent.append(message)

    def debug(self, name, image):
        self.images[name] = image

    def close(self):
        pass


def main():
    recording = Recording(FOLDER)
    engine = Engine(recording, camera=recording, screen=recording)
    assert engine.predictor is not None, "the recording has no calibration file"
    video, with_hand = None, 0
    for number in range(len(recording.frames) - 1):
        pointers = engine.step()
        if pointers is None:
            continue
        with_hand += bool(pointers)
        print(number, " ".join(f"#{p['id']} ({p['x']:.3f}, {p['y']:.3f}) {p['pose']}{' DOWN' if p['down'] else ''}" for p in pointers) or "-")
        if "--video" in sys.argv:
            image = recording.images.get("overlay")
            if image is not None:
                if video is None:
                    video = cv2.VideoWriter(str(FOLDER / "overlay.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 30, image.shape[1::-1])
                video.write(image)
    if video is not None:
        video.release()
    print(f"{len(recording.frames)} frames, {with_hand} with a hand reported")


if __name__ == "__main__":
    main()
