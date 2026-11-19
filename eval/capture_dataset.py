"""Records the development dataset on the real rig: every pattern and test
picture is projected and photographed by each camera.

    python -m eval.capture_dataset runs/ds1 0 android

Layout: <out>/<name>/screen.png, <out>/<name>/<camera>_<k>.jpg, <out>/index.json
"""
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from eval.content import H, W, contents, fake_hand, occlude
from visiontouch.app import run
from visiontouch.calibrate import colour_tiles, marker_pattern
from visiontouch.camera import Camera

OUT = Path(sys.argv[1])
SOURCES = sys.argv[2:] or ["0"]


def main(server):
    assert server.wait_for_stage(), "stage window did not connect"
    cams = {s.split(":")[0]: Camera(s) for s in SOURCES}
    index = {}

    def shoot(name, image, settle, extra=None):
        folder = OUT / name
        folder.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(folder / "screen.png"), image)
        assert server.show(image), "stage did not paint"
        time.sleep(settle)
        for cam_name, cam in cams.items():
            last = 0
            for k in range(3):
                frame, _, last = cam.read(newer_than=last)
                cv2.imwrite(str(folder / f"{cam_name}_{k}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 96])
        index[name] = extra or {}

    # Calibration patterns: the marker grid, then colour mosaics.
    shoot("cal_markers", marker_pattern(W, H)[0], 1.5)
    for seed in range(6):
        shoot(f"cal_tiles_{seed}", colour_tiles(W, H, seed), 1.2 if seed == 0 else 0.7)

    # Test pictures: clean, then with a fake shadow, then with a fake lit hand.
    rng = np.random.default_rng(7)
    for name, image in contents().items():
        shoot(f"{name}__clean", image, 1.5)
        for kind in ("shadow", "hand"):
            mask, tip = fake_hand(rng)
            shoot(f"{name}__{kind}", occlude(image, mask, kind), 0.6, {"tip": tip, "kind": kind})
            cv2.imwrite(str(OUT / f"{name}__{kind}" / "mask.png"), mask)
        print(name, flush=True)

    server.show(None)
    (OUT / "index.json").write_text(json.dumps(index, indent=1))
    for cam in cams.values():
        cam.close()


if __name__ == "__main__":
    run(main)
