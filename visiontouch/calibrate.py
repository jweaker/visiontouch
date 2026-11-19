"""Calibration patterns and the maths that turns their photos into a model.

Geometry: a grid of ArUco markers gives hundreds of screen<->camera point
pairs; a homography (plane-to-plane perspective map) is fitted to them.
"""
import cv2
import numpy as np

DICTIONARY = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_100)
GRID = (10, 6)  # marker columns, rows


def marker_pattern(w, h):
    """White image with a grid of markers. Returns (image, {id: 4x2 corners})
    with corners in screen pixels, clockwise from top-left like the detector."""
    image = np.full((h, w, 3), 255, np.uint8)
    cell = min(w / GRID[0], h / GRID[1])
    side = int(cell * 0.7)
    x0, y0 = (w - cell * GRID[0]) / 2, (h - cell * GRID[1]) / 2
    corners = {}
    for i in range(GRID[0] * GRID[1]):
        x = int(x0 + (i % GRID[0] + 0.15) * cell)
        y = int(y0 + (i // GRID[0] + 0.15) * cell)
        image[y:y + side, x:x + side] = cv2.aruco.generateImageMarker(DICTIONARY, i, side)[..., None]
        corners[i] = np.float32([[x, y], [x + side, y], [x + side, y + side], [x, y + side]])
    return image, corners


def find_homography(camera_image, corners):
    """Detect the marker grid in a camera image. Returns (H, error, count):
    H maps camera pixels to screen pixels, error is the RMS reprojection error
    in screen pixels, count the number of markers used. H is None on failure."""
    gray = cv2.cvtColor(camera_image, cv2.COLOR_BGR2GRAY) if camera_image.ndim == 3 else camera_image
    parameters = cv2.aruco.DetectorParameters()
    parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    found, ids, _ = cv2.aruco.ArucoDetector(DICTIONARY, parameters).detectMarkers(gray)
    if ids is None or len(ids) < 4:
        return None, float("inf"), 0 if ids is None else len(ids)
    camera = np.concatenate([c.reshape(4, 2) for c in found])
    screen = np.concatenate([corners[int(i)] for i in ids.ravel()])
    H, inliers = cv2.findHomography(camera, screen, cv2.RANSAC, 4.0)
    if H is None:
        return None, float("inf"), len(ids)
    keep = inliers.ravel() == 1
    projected = cv2.perspectiveTransform(camera[keep][None], H)[0]
    error = float(np.sqrt(np.mean(np.sum((projected - screen[keep]) ** 2, axis=1))))
    return H, error, int(keep.sum() // 4)


def colour_tiles(w, h, seed):
    """A 16x9 mosaic of random colours (every fourth tile a grey). A few of
    these show the camera hundreds of screen colours while the average
    brightness stays about the same, so its auto-exposure does not move."""
    rng = np.random.default_rng(seed)
    colours = rng.integers(0, 256, (9, 16, 3))
    greys = rng.integers(0, 256, (9, 16, 1))
    colours = np.where(rng.random((9, 16, 1)) < 0.25, greys, colours)
    corners = [(b, g, r) for b in (0, 255) for g in (0, 255) for r in (0, 255)]  # the extremes, always present
    for (y, x), colour in zip(rng.permutation(9 * 16)[:8].reshape(-1, 1) // [16, 1] % [9, 16], corners):
        colours[y, x] = colour
    return cv2.resize(colours.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST)


if __name__ == "__main__":  # self-check: a synthetic camera view must give back its homography
    pattern, corners = marker_pattern(1920, 1080)
    true = np.float32([[0.45, 0.04, 380], [-0.03, 0.5, 160], [-2e-5, 3e-5, 1]])  # screen -> camera
    view = cv2.warpPerspective(pattern, true, (1920, 1080), borderValue=(40, 40, 40))
    H, error, count = find_homography(view, corners)
    assert H is not None and count >= 50 and error < 1.5, (error, count)
    corner = cv2.perspectiveTransform(np.float32([[[1920, 1080]]]), np.linalg.inv(H))[0, 0]
    expected = cv2.perspectiveTransform(np.float32([[[1920, 1080]]]), true)[0, 0]
    assert np.linalg.norm(corner - expected) < 1.0, (corner, expected)
    print(f"ok: {count} markers, {error:.2f} px RMS")
