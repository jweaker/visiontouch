"""Automatic keystone correction.

A slanted projector throws a lopsided quadrilateral. To show a true rectangle
we draw the picture pre-distorted, inside the largest upright rectangle that
fits in that quadrilateral. "Upright" needs a reference on the wall: the frame
of the projection screen if the camera can see one, otherwise the camera's own
view (which is right for a viewer standing near the camera).
"""
import cv2
import numpy as np


def _unit(v):
    return v / (np.linalg.norm(v) + 1e-9)


def find_frame(camera_image, quad):
    """Find the edge of the projection screen around the projected picture.

    quad: the picture's corners in the camera image (TL, TR, BR, BL). From
    points along each side we walk outwards and stop at the first strong edge
    (screen surface -> dark border), then fit a line through the stops.
    Returns the frame's 4 corners (TL, TR, BR, BL) or None.
    """
    grey = cv2.cvtColor(camera_image, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
    grey = cv2.GaussianBlur(grey ** 0.35, (0, 0), 2)  # gamma < 1 lifts the dim surroundings
    h, w = grey.shape
    centre = quad.mean(0)
    reach = int(0.6 * np.linalg.norm(quad[1] - quad[0]))
    lines = []
    for i in range(4):
        a, b = quad[i], quad[(i + 1) % 4]
        normal = _unit(np.array([b[1] - a[1], a[0] - b[0]]))
        if normal @ (centre - a) > 0:
            normal = -normal  # point away from the picture
        stops = []
        for t in np.linspace(0.12, 0.88, 40):
            start = a + t * (b - a)
            steps = np.arange(10, reach)
            xs, ys = start[0] + steps * normal[0], start[1] + steps * normal[1]
            ok = (xs >= 0) & (xs < w - 1) & (ys >= 0) & (ys < h - 1)
            if ok.sum() < 12:
                continue
            profile = grey[ys[ok].astype(int), xs[ok].astype(int)]
            change = np.abs(profile[6:] - profile[:-6])  # brightness change over 6 px
            hits = np.flatnonzero(change > 0.09)
            if len(hits):
                d = steps[ok][hits[0] + 3]
                stops.append(start + d * normal)
        if len(stops) < 15:
            return None
        stops = np.float32(stops)
        vx, vy, x0, y0 = cv2.fitLine(stops, cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
        direction, point = np.array([vx, vy]), np.array([x0, y0])
        distance = np.abs((stops - point) @ np.array([-vy, vx]))
        angle = np.degrees(np.arccos(min(abs(direction @ _unit(b - a)), 1.0)))
        if np.mean(distance < 4) < 0.6 or angle > 20:
            return None  # no clean straight edge on this side
        lines.append((point, direction))
    corners = []
    for i in range(4):  # corner i is where side i-1 meets side i
        (p1, d1), (p2, d2) = lines[i - 1], lines[i]
        s = np.linalg.solve(np.array([d1, -d2]).T, p2 - p1)
        corners.append(p1 + s[0] * d1)
    return np.float32(corners)


def rectangle_aspect(corners, image_size, fov_degrees=65):
    """Width/height of a real rectangle from its perspective image, assuming a
    camera with square pixels and this horizontal field of view. The answer
    changes little with the field of view unless the view is very oblique."""
    w, h = image_size
    f = w / 2 / np.tan(np.radians(fov_degrees) / 2)
    k_inv = np.linalg.inv(np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1.0]]))
    to_image = cv2.getPerspectiveTransform(np.float32([[0, 0], [1, 0], [1, 1], [0, 1]]), np.float32(corners))
    m = k_inv @ to_image
    return float(np.linalg.norm(m[:, 0]) / np.linalg.norm(m[:, 1]))


def _inside(points, polygon):
    """True if every point is inside the convex polygon."""
    edges = np.roll(polygon, -1, axis=0) - polygon
    sign = np.sign(edges[0, 0] * edges[1, 1] - edges[0, 1] * edges[1, 0])
    rel = points[:, None, :] - polygon[None]
    return bool(np.all(sign * (edges[None, :, 0] * rel[..., 1] - edges[None, :, 1] * rel[..., 0]) >= 0))


def largest_rectangle(polygon, aspect):
    """Largest axis-aligned rectangle of the given width/height ratio inside a
    convex quadrilateral. Returns (x, y, width, height). Brute force over
    centres, bisection on size: small and plenty fast."""
    lo, hi = polygon.min(0), polygon.max(0)
    best = (0.0, 0.0, 0.0, 0.0)
    for cx in np.linspace(lo[0], hi[0], 41):
        for cy in np.linspace(lo[1], hi[1], 41):
            small, big = 0.0, hi[1] - lo[1]
            for _ in range(18):
                height = (small + big) / 2
                half = np.array([aspect * height / 2, height / 2])
                box = np.array([[cx - half[0], cy - half[1]], [cx + half[0], cy - half[1]],
                                [cx + half[0], cy + half[1]], [cx - half[0], cy + half[1]]])
                small, big = (height, big) if _inside(box, polygon) else (small, height)
            if small > best[3]:
                best = (cx - aspect * small / 2, cy - small / 2, aspect * small, small)
    return best


def correction(cam_to_screen, screen_size, camera_size, frame=None):
    """The 3x3 matrix that maps the content box (screen_size pixels) to screen
    pixels so that it lands as an upright rectangle on the wall."""
    w, h = screen_size
    screen_corners = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    quad = cv2.perspectiveTransform(screen_corners[None], np.linalg.inv(cam_to_screen))[0]
    if frame is None:
        cam_to_wall = np.eye(3)  # treat the camera's view as "straight"
    else:
        aspect = rectangle_aspect(frame, camera_size)
        cam_to_wall = cv2.getPerspectiveTransform(np.float32(frame), np.float32([[0, 0], [aspect, 0], [aspect, 1], [0, 1]]))
    on_wall = cv2.perspectiveTransform(quad[None], cam_to_wall)[0]
    x, y, rw, rh = largest_rectangle(on_wall.astype(np.float64), w / h)
    content_to_wall = np.array([[rw / w, 0, x], [0, rh / h, y], [0, 0, 1.0]])
    return cam_to_screen @ np.linalg.inv(cam_to_wall) @ content_to_wall


if __name__ == "__main__":  # self-check with a synthetic wall
    # A real pinhole camera (65 degree field of view) looking up and sideways at the wall.
    f = 960 / np.tan(np.radians(65) / 2)
    rotation = cv2.Rodrigues(np.array([0.35, -0.2, 0.03]))[0]
    wall_to_cam = np.array([[f, 0, 960], [0, f, 540], [0, 0, 1.0]]) @ np.column_stack([rotation[:, 0], rotation[:, 1], [-0.9, -0.2, 2.2]])
    frame = cv2.perspectiveTransform(np.float32([[[0, 0], [16 / 9, 0], [16 / 9, 1], [0, 1]]]), wall_to_cam)[0]
    slanted = np.float32([[0.25, 0.12], [1.5, 0.2], [1.45, 0.85], [0.3, 0.9]])  # where the projector lands on the wall
    wall_to_screen = cv2.getPerspectiveTransform(slanted, np.float32([[0, 0], [1920, 0], [1920, 1080], [0, 1080]]))
    cam_to_screen = wall_to_screen @ np.linalg.inv(wall_to_cam)
    m = correction(cam_to_screen, (1920, 1080), (1920, 1080), frame)
    corners = cv2.perspectiveTransform(np.float32([[[0, 0], [1920, 0], [1920, 1080], [0, 1080]]]), np.linalg.inv(wall_to_screen) @ m)[0]
    width, height = corners[1, 0] - corners[0, 0], corners[3, 1] - corners[0, 1]
    assert abs(corners[0, 1] - corners[1, 1]) < 2e-3 and abs(corners[0, 0] - corners[3, 0]) < 2e-3, corners  # upright
    assert abs(width / height - 16 / 9) < 0.08, width / height  # right shape (field of view is only assumed)
    assert _inside(corners.astype(np.float64) * 0.999 + corners.mean(0) * 0.001, slanted.astype(np.float64))  # fits
    assert largest_rectangle(np.array([[0, 0], [2, 0], [2, 1], [0, 1.0]]), 2.0)[3] > 0.97
    print(f"ok: corrected picture {width:.2f} x {height:.2f} wall units")
