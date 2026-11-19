"""Measures keystone correction on the real rig.

    python -m eval.keystone_test [camera]

Projects the marker grid twice, plain and pre-distorted by the correction, and
measures in each case how far the picture's edges are from parallel to the
screen frame (0 degrees = perfectly square). Then checks that a synthetic hand
drawn in the corrected picture is reported at the right place.
"""
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from eval.content import fake_hand, occlude
from eval.live_test import PretendScreen
from visiontouch.app import run
from visiontouch.calibrate import find_homography, marker_pattern
from visiontouch.engine import Engine
from visiontouch.keystone import find_frame, rectangle_aspect

CAMERA = sys.argv[1] if len(sys.argv) > 1 else "0"
OUT = Path("runs/keystone")


def tilt(corners):
    """Largest angle (degrees) between the quadrilateral's sides and the axes."""
    angles = []
    for i in range(4):
        dx, dy = corners[(i + 1) % 4] - corners[i]
        angle = abs(np.degrees(np.arctan2(dy, dx))) % 180
        angles.append(min(angle, abs(angle - 90), abs(angle - 180)))
    return float(max(angles))


def main(server):
    assert server.wait_for_stage(), "stage window did not connect"
    OUT.mkdir(parents=True, exist_ok=True)
    engine = Engine(server, CAMERA)
    assert engine.calibrate(), engine.message
    print(engine.message, flush=True)
    w, h = engine.screen.size
    pattern, corners = marker_pattern(w, h)
    box = np.float32([[[0, 0], [w, 0], [w, h], [0, h]]])
    report = {"camera": CAMERA, "calibration": engine.message}

    server.show(np.full((h, w, 3), 255, np.uint8))
    photo = engine._fresh_frame(1.0)
    quad = cv2.perspectiveTransform(box, np.linalg.inv(engine.predictor.cam_to_screen))[0]
    frame = find_frame(photo, quad)
    assert frame is not None, "screen frame not found: nothing to measure against"
    aspect = rectangle_aspect(frame, photo.shape[1::-1])
    cam_to_wall = cv2.getPerspectiveTransform(frame, np.float32([[0, 0], [aspect, 0], [aspect, 1], [0, 1]]))
    for label, picture in (("plain", pattern), ("corrected", cv2.warpPerspective(pattern, engine.warp, (w, h)))):
        server.show(picture)
        photo = engine._fresh_frame(1.2)
        cam_to_pattern, error, count = find_homography(photo, corners)
        assert cam_to_pattern is not None, f"markers not found in the {label} picture"
        on_wall = cv2.perspectiveTransform(cv2.perspectiveTransform(box, np.linalg.inv(cam_to_pattern)), cam_to_wall)[0]
        width = np.linalg.norm(on_wall[1] - on_wall[0]) + np.linalg.norm(on_wall[2] - on_wall[3])
        height = np.linalg.norm(on_wall[3] - on_wall[0]) + np.linalg.norm(on_wall[2] - on_wall[1])
        report[label] = {"tilt_degrees": tilt(on_wall), "aspect": float(width / height), "markers": count}
        print(label, report[label], flush=True)
        cv2.imwrite(str(OUT / f"{label}_{CAMERA.split(':')[0]}.jpg"), photo)

    # A synthetic hand drawn in the corrected picture must come back in content coordinates.
    pretend, rng, errors = PretendScreen(engine.screen), np.random.default_rng(5), []
    engine.screen = pretend
    plain = np.full((h, w, 3), 240, np.uint8)
    server.show(cv2.warpPerspective(plain, engine.warp, (w, h)))
    time.sleep(1.0)
    pretend.freeze(engine, cv2.warpPerspective(plain, engine.warp, (w, h)))
    for trial in range(4):
        mask, tip = pretend.clear_of(lambda: fake_hand(rng))
        server.show(cv2.warpPerspective(occlude(plain, mask, "shadow"), engine.warp, (w, h)))
        time.sleep(0.9)
        engine.tracker.pointers.clear()
        end = time.monotonic() + 1.0
        while time.monotonic() < end:
            pointers = engine.step()
            if pointers:
                errors.append(float(np.hypot(pointers[0]["x"] * w - tip[0], pointers[0]["y"] * h - tip[1])))
    report["pointer_error_px"] = {"median": float(np.median(errors)) if errors else None, "frames": len(errors)}
    print("pointer in corrected picture:", report["pointer_error_px"], flush=True)
    server.show(None)
    (OUT / f"report_{CAMERA.split(':')[0]}.json").write_text(json.dumps(report, indent=1))
    engine.camera.close()


if __name__ == "__main__":
    run(main)
