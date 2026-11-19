"""From the residual image to hands.

Classical path: threshold -> morphology -> connected components -> fingertip.
An arm always enters the picture from an edge, so the fingertip is the point
of the blob farthest from where the blob crosses the edge.

Learned path: MediaPipe Hands looks at a zoomed crop around each blob and
returns 21 landmarks, from which the pose (point, pinch, palm, fist) is read.
"""
from pathlib import Path

import cv2
import numpy as np

LOW, HIGH = 8, 18  # residual thresholds (grey levels): weak evidence, strong evidence
MIN_AREA = 0.0015  # smallest blob, as a fraction of the working image
GAP = 9  # pieces closer than this (working pixels) count as one blob
THICK = 7  # a blob must be at least this wide somewhere (working pixels)
SOLID = 5  # parts of a blob narrower than this (working pixels) cannot be the fingertip
MODEL = Path(__file__).parent / "models" / "hand_landmarker.task"


def clean_mask(residual, sensitivity=1.0):
    """From the residual to blobs. Returns (mask, labels, blob numbers).

    1. Hysteresis threshold plus morphology: a piece counts as a real object
       if it has strong pixels, is big enough, and is wide somewhere (an arm
       is; leftovers along the outlines of drawn shapes are thin strips).
    2. Pieces near each other are one blob, and a blob is kept if it contains
       a real object. So a fingertip cut off from its hand (the picture is
       dark there, or a drawn line crosses the finger) is still part of the
       arm, while a lone small piece is dropped.
    3. Thin parts next to the blob are restored and the margin lost to the
       residual's edge tolerance is given back.

    `sensitivity` above 1 lowers both thresholds (finds fainter hands, risks
    more false alarms); below 1 raises them."""
    low, high = LOW / sensitivity, HIGH / sensitivity
    raw = (residual > low).astype(np.uint8)
    weak = cv2.morphologyEx(raw, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    weak = cv2.morphologyEx(weak, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    count, pieces, stats, _ = cv2.connectedComponentsWithStats(weak, connectivity=8)
    strong = np.bincount(pieces[residual > high], minlength=count)
    wide = np.bincount(pieces[cv2.erode(weak, np.ones((THICK, THICK), np.uint8)) > 0], minlength=count) > 0
    real = (stats[:, cv2.CC_STAT_AREA] >= MIN_AREA * residual.size) & (strong >= 0.2 * stats[:, cv2.CC_STAT_AREA]) & wide
    real[0] = False
    count, groups = cv2.connectedComponents(cv2.dilate(weak, np.ones((GAP, GAP), np.uint8)), connectivity=8)
    kept_groups = np.zeros(count, bool)
    kept_groups[groups[real[pieces]]] = True
    kept = (weak > 0) & kept_groups[groups]
    kept = kept.astype(np.uint8)
    for _ in range(4):  # grow back along thin parts, up to 12 px
        kept = cv2.dilate(kept, np.ones((7, 7), np.uint8)) & (raw | kept)
    kept = cv2.dilate(kept, np.ones((5, 5), np.uint8))
    groups = np.where(kept > 0, groups, 0)
    return kept > 0, groups, np.unique(groups[groups > 0])


def find_tips(labels, blobs, inside):
    """Fingertip of every blob that reaches the edge of the projected area.
    Returns a list of dicts: tip (x, y), entry (x, y), area, label."""
    core = cv2.erode(inside.astype(np.uint8), np.ones((9, 9), np.uint8), borderType=cv2.BORDER_CONSTANT, borderValue=0)
    edge = inside & (core == 0)
    # The tip is looked for on the solid part of the blob only. A finger is
    # several pixels wide; a thin line stuck to it (the app's own cursor ring,
    # the outline of a button) is not, and must not pull the tip away.
    solid = cv2.morphologyEx((labels > 0).astype(np.uint8), cv2.MORPH_OPEN, np.ones((SOLID, SOLID), np.uint8)) > 0
    hands = []
    for label in blobs:
        ys, xs = np.nonzero(labels == label)
        on_edge = edge[ys, xs]
        if on_edge.sum() < 5:
            continue  # an island in the middle of the screen is not an arm
        entry = np.array([xs[on_edge].mean(), ys[on_edge].mean()])
        ys, xs = np.nonzero((labels == label) & solid)
        if len(xs) < 3:
            continue
        distance = np.hypot(xs - entry[0], ys - entry[1])
        far = distance >= np.partition(distance, -max(len(distance) // 100, 3))[-max(len(distance) // 100, 3)]
        tip = np.array([xs[far].mean(), ys[far].mean()])
        hands.append({"tip": tip, "entry": entry, "area": len(xs), "label": int(label)})
    return hands


class Landmarker:
    """MediaPipe Hands on a zoomed crop around a blob's fingertip."""

    def __init__(self):
        import mediapipe as mp

        options = mp.tasks.vision.HandLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(MODEL)),
            num_hands=1, min_hand_detection_confidence=0.3, min_hand_presence_confidence=0.3,
        )
        self._mp = mp
        self._model = mp.tasks.vision.HandLandmarker.create_from_options(options)

    def detect(self, frame, centre, half):
        """Look for a hand in the square of half-size `half` around `centre`
        (camera pixels). Returns 21 x 2 landmark positions in camera pixels, or None."""
        x0, y0, side = int(centre[0] - half), int(centre[1] - half), int(2 * half)
        if side < 32:
            return None
        # Cut the square out through an affine map: parts beyond the frame
        # edge are filled in, so the crop stays square and the hand unstretched.
        scale = 320 / side
        to_crop = np.float32([[scale, 0, -x0 * scale], [0, scale, -y0 * scale]])
        crop = cv2.warpAffine(frame, to_crop, (320, 320), borderMode=cv2.BORDER_REPLICATE)
        crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        result = self._model.detect(self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=np.ascontiguousarray(crop)))
        if not result.hand_landmarks:
            return None
        points = np.array([[p.x, p.y] for p in result.hand_landmarks[0]])
        return points * side + [x0, y0]


def read_pose(points):
    """Pose and pointing position from 21 landmarks (any pixel units).
    Returns (pose, (x, y)): 'pinch' at the thumb/index meeting point, 'palm'
    and 'fist' at the palm centre, 'point' at the index fingertip."""
    wrist, palm = points[0], points[9]
    size = np.linalg.norm(palm - wrist) + 1e-6
    extended = [np.linalg.norm(points[tip] - wrist) > 1.25 * np.linalg.norm(points[joint] - wrist)
                for tip, joint in ((8, 6), (12, 10), (16, 14), (20, 18))]
    if np.linalg.norm(points[4] - points[8]) < 0.35 * size:
        return "pinch", (points[4] + points[8]) / 2
    if all(extended):
        return "palm", palm
    if not any(extended):
        return "fist", palm
    return "point", points[8]


if __name__ == "__main__":  # self-check on a synthetic arm
    residual = np.zeros((300, 500), np.float32)
    cv2.line(residual, (250, 299), (300, 120), 30.0, 24)
    residual[10:12, 10:200] = 30  # a thin edge leftover: must be removed
    inside = np.ones(residual.shape, bool)
    mask, labels, blobs = clean_mask(residual)
    hands = find_tips(labels, blobs, inside)
    assert len(hands) == 1 and np.linalg.norm(hands[0]["tip"] - [300, 112]) < 12, hands
    residual[198:203] = 0  # the arm crosses a dark line and disappears there: still one arm
    assert np.linalg.norm(find_tips(*clean_mask(residual)[1:], inside)[0]["tip"] - [300, 112]) < 12
    assert not mask[10, 100]
    square = np.zeros((21, 2)); square[9] = [0, -100]; square[[6, 10, 14, 18]] = [0, -150]; square[[8, 12, 16, 20]] = [0, -230]; square[4] = [80, -60]
    assert read_pose(square)[0] == "palm"
    square[4] = square[8] + [5, 5]
    assert read_pose(square)[0] == "pinch"
    print("ok")
