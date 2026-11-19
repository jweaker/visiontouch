"""Test content for the dataset: the kinds of pictures VisionTouch has to work
in front of, plus synthetic hands with known fingertip positions."""
from pathlib import Path

import cv2
import numpy as np

W, H = 1920, 1080
FONT = cv2.FONT_HERSHEY_SIMPLEX


def _slide(bg, fg):
    img = np.full((H, W, 3), bg, np.uint8)
    cv2.putText(img, "Image Subtraction", (120, 190), FONT, 3.2, fg, 8, cv2.LINE_AA)
    for i, line in enumerate(["g(x, y) = f(x, y) - h(x, y)", "Used to find what changed", "Threshold the difference"]):
        cv2.putText(img, "- " + line, (150, 360 + i * 120), FONT, 1.8, fg, 4, cv2.LINE_AA)
    for i, (height, colour) in enumerate([(300, (60, 80, 230)), (180, (60, 180, 60)), (380, (230, 140, 40))]):
        cv2.rectangle(img, (1250 + i * 170, 900 - height), (1380 + i * 170, 900), colour, -1)
    return img


def _text_page():
    img = np.full((H, W, 3), 250, np.uint8)
    for y in range(60, H - 20, 34):
        cv2.putText(img, "The quick brown fox jumps over the lazy dog 0123456789 " * 2, (40, y), FONT, 0.8, (20, 20, 20), 2, cv2.LINE_AA)
    return img


def _board():
    img = np.full((H, W, 3), 255, np.uint8)
    rng = np.random.default_rng(1)
    for colour in [(220, 60, 40), (40, 40, 220), (40, 160, 40), (20, 20, 20)]:
        pts = np.cumsum(rng.normal(0, 60, (40, 2)), axis=0) + rng.uniform([300, 250], [1600, 800])
        cv2.polylines(img, [pts.astype(np.int32)], False, colour, 10, cv2.LINE_AA)
    return img


def _balloons():
    img = np.full((H, W, 3), (245, 225, 200), np.uint8)
    rng = np.random.default_rng(2)
    for colour in [(60, 60, 235), (60, 200, 250), (80, 190, 80), (230, 120, 60), (200, 80, 200)] * 2:
        centre = (int(rng.uniform(150, W - 150)), int(rng.uniform(150, H - 150)))
        cv2.ellipse(img, centre, (85, 105), 0, 0, 360, colour, -1, cv2.LINE_AA)
    return img


def contents():
    """name -> 1920x1080 BGR image."""
    ramp = np.tile(np.linspace(0, 255, W, dtype=np.uint8), (H, 1))
    out = {
        "white": np.full((H, W, 3), 255, np.uint8),
        "light": np.full((H, W, 3), 200, np.uint8),
        "mid": np.full((H, W, 3), 128, np.uint8),
        "dark": np.full((H, W, 3), 48, np.uint8),
        "black": np.zeros((H, W, 3), np.uint8),
        "pastel": np.full((H, W, 3), (235, 215, 190), np.uint8),
        "red": np.full((H, W, 3), (40, 40, 230), np.uint8),
        "green": np.full((H, W, 3), (60, 200, 60), np.uint8),
        "ramp": cv2.merge([ramp] * 3),
        "colour_ramp": cv2.merge([ramp, ramp[::-1].copy(), np.rot90(np.tile(np.linspace(0, 255, H, dtype=np.uint8), (W, 1))).copy()]),
        "checker": np.kron((np.indices((27, 48)).sum(0) % 2 * 255).astype(np.uint8), np.ones((40, 40), np.uint8))[..., None].repeat(3, 2),
        "slide_light": _slide(255, (30, 30, 30)),
        "slide_dark": _slide(30, (235, 235, 235)),
        "text": _text_page(),
        "board": _board(),
        "balloons": _balloons(),
    }
    for path in sorted(Path("runs/content").glob("*.*")):  # photos and screenshots dropped here
        image = cv2.imread(str(path))
        if image is not None:
            out[path.stem] = cv2.resize(image, (W, H), interpolation=cv2.INTER_AREA)
    return out


def fake_hand(rng):
    """A pointing hand with its arm entering from an edge of the screen.
    Returns (mask uint8 HxW, fingertip (x, y))."""
    mask = np.zeros((H, W), np.uint8)
    tip = np.array([rng.uniform(200, W - 200), rng.uniform(150, H - 250)])
    side = rng.choice(["bottom", "left", "right"])
    entry = {"bottom": [tip[0] + rng.uniform(-300, 300), H + 40],
             "left": [-40, tip[1] + rng.uniform(0, 300)],
             "right": [W + 40, tip[1] + rng.uniform(0, 300)]}[side]
    entry = np.array(entry)
    direction = (tip - entry) / np.linalg.norm(tip - entry)
    palm = tip - direction * 150
    to_int = lambda p: (int(p[0]), int(p[1]))
    cv2.line(mask, to_int(entry), to_int(palm - direction * 40), 255, 85, cv2.LINE_AA)  # forearm
    cv2.circle(mask, to_int(palm), 62, 255, -1, cv2.LINE_AA)  # palm with folded fingers
    cv2.line(mask, to_int(palm), to_int(tip - direction * 11), 255, 22, cv2.LINE_AA)  # index finger
    return mask, (float(tip[0]), float(tip[1]))


def occlude(image, mask, kind):
    """Paint the fake hand into the picture the way a projector would show it.
    'shadow': no projector light. 'hand': the content reflected by skin."""
    factor = {"shadow": np.float32([0, 0, 0]), "hand": np.float32([0.42, 0.52, 0.68])}[kind]
    alpha = (mask.astype(np.float32) / 255)[..., None]
    return (image * (1 - alpha) + image * factor * alpha).astype(np.uint8)
