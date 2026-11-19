"""Scores the predictor on a recorded dataset (see capture_dataset.py).

    python -m eval.score_dataset runs/ds1 runs/ds1b 0 android [--view name ...]

The second folder holds the calibration captures (markers and colour mosaics).

For every test picture: how many clean pixels are wrongly flagged (false
positives) and how much of the fake shadow / fake hand is found (recall).
"""
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from visiontouch.calibrate import find_homography, marker_pattern
from visiontouch.predict import SCREEN_SCALE, Predictor

THRESHOLD = 10


def load(folder, cam, k=1):
    return cv2.imread(str(folder / f"{cam}_{k}.jpg"))


def small(image):
    return cv2.resize(image, None, fx=SCREEN_SCALE, fy=SCREEN_SCALE, interpolation=cv2.INTER_AREA)


def main(root, cal, cams, view, only=()):
    index = json.loads((root / "index.json").read_text())
    names = sorted(k[:-7] for k in index if k.endswith("__clean"))
    names = [n for n in names if not only or n in only]
    pattern, corners = marker_pattern(1920, 1080)
    for cam in cams:
        H, error, count = find_homography(load(cal / "cal_markers", cam), corners)
        tiles = [(small(cv2.imread(str(f / "screen.png"))), load(f, cam)) for f in sorted(cal.glob("cal_tiles_*"))]
        print(f"== camera {cam}: {count} markers, {error:.2f} px")
        print(f"{'picture':<12} {'clean FP':>8} | {'shadow':>13} | {'hand':>13}   (recall / FP)")
        totals, times, panels = [], [], []
        for name in names:
            screen = small(cv2.imread(str(root / f"{name}__clean" / "screen.png")))
            row = f"{name:<12}"
            for kind in ("clean", "shadow", "hand"):
                p = Predictor(H, (1920, 1080), (1920, 1080))
                p.calibrate_colour(tiles)
                p.residual(screen, load(root / f"{name}__{kind}", cam, 0))  # warm-up frame, as in live use
                frame = load(root / f"{name}__{kind}", cam)
                start = time.perf_counter()
                residual, predicted, observed = p.residual(screen, frame)
                times.append(time.perf_counter() - start)
                hit = residual > THRESHOLD
                if kind == "clean":
                    fp = hit[p.inside].mean()
                    row += f" {fp:8.3f} |"
                    totals.append(("clean", fp, 0))
                else:
                    truth = cv2.imread(str(root / f"{name}__{kind}" / "mask.png"), 0)
                    truth = cv2.warpPerspective(truth, p.screen_to_work, p.size) > 128
                    truth &= p.inside
                    recall, fp = hit[truth].mean(), hit[~truth & p.inside].mean()
                    row += f" {recall:5.2f} / {fp:5.3f} |"
                    totals.append((kind, fp, recall))
                if f"{name}__{kind}" in view:
                    heat = cv2.applyColorMap(np.clip(residual * 8, 0, 255).astype(np.uint8), cv2.COLORMAP_JET)
                    mask = cv2.merge([hit.astype(np.uint8) * 255] * 3)
                    panels.append(np.hstack([observed.clip(0, 255).astype(np.uint8), predicted.clip(0, 255).astype(np.uint8), heat, mask]))
            print(row)
        for kind in ("clean", "shadow", "hand"):
            rows = [(fp, rec) for k, fp, rec in totals if k == kind]
            print(f"  {kind:<7} mean FP {np.mean([r[0] for r in rows]):.3f}  mean recall {np.mean([r[1] for r in rows]):.2f}")
        print(f"  time per frame {1000 * np.median(times):.1f} ms, working size {p.size}")
        if panels:
            cv2.imwrite(str(root / f"view_{cam}.jpg"), np.vstack(panels))


if __name__ == "__main__":
    args = sys.argv[1:]
    view = args[args.index("--view") + 1:] if "--view" in args else []
    args = args[:args.index("--view")] if "--view" in args else args
    main(Path(args[0]), Path(args[1]), args[2:] or ["0"], view)
