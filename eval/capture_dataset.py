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
from visiontouch.calibrate import marker_pattern, stripes
from visiontouch.camera import Camera

OUT = Path(sys.argv[1])
SOURCES = sys.argv[2:] or ["0"]
GREYS = [(v, v, v) for v in np.linspace(0, 255, 8).astype(int).tolist()]
COLOURS = [(0, 0, 0), (0, 0, 255), (0, 255, 0), (255, 0, 0), (255, 255, 0), (255, 0, 255), (0, 255, 255), (255, 255, 255)]


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

    # Calibration patterns. All but the first keep the average brightness constant.
    shoot("cal_markers", marker_pattern(W, H)[0], 1.5)
    for shift in range(8):
        shoot(f"cal_grey_{shift}", stripes(W, H, GREYS, shift), 1.2 if shift == 0 else 0.6)
    for shift in range(8):
        shoot(f"cal_colour_{shift}", stripes(W, H, COLOURS, shift), 1.2 if shift == 0 else 0.6)

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
