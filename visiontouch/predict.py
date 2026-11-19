"""Background subtraction against a predicted background.

The screen image is known, so instead of remembering what the wall looked
like, we predict what the camera should see right now and flag whatever
disagrees (a hand, an arm, their shadow).

  1. Geometry: warp the screen picture into the camera's view (homography).
  2. Colour map: a cubic polynomial, fitted at calibration, that says how each
     screen colour comes out in the camera.
  3. Exposure: the camera keeps changing its exposure and white balance, so
     every frame the colour map is re-fitted on the colours currently on
     screen, pulled towards the calibrated one for all other colours.
  4. Banding: the projector flashes red, green and blue in turn while the
     camera reads its rows one after another, so each row catches a slightly
     different mix (rainbow bands). Per row we solve for the three colour
     strengths; the colour map's derivatives say what each one changes.
  5. Residual: distance of each observed pixel from the range of predicted
     values in its neighbourhood, which forgives small misalignment and blur.
"""
import cv2
import numpy as np

SCREEN_SCALE = 0.5  # the screen picture is handled at half resolution
# Powers of (blue, green, red) for every term of a cubic polynomial: 20 terms.
# Tuning knobs for the banding correction.
ROW_RIDGE = 0.05  # how strongly per-row colour strengths are held at "no change"
ROW_LIMIT = 0.3  # largest allowed change in a row
BAND_SLACK = 0.04  # extra tolerance where banding would change the pixel most
CALIBRATION_PULL = 1e-2  # smoothness of the calibrated colour map
NO_CHANGE = np.vstack([np.eye(3), np.zeros((1, 3))]).astype(np.float32)  # exposure matrix + offset
EXPONENTS = np.float32([(i, j, k) for i in range(4) for j in range(4) for k in range(4) if i + j + k <= 3])


def _features(colours):
    """Polynomial terms for N x 3 uint8 screen colours -> N x 20 float32."""
    s = colours.astype(np.float32) / 255
    powers = [np.ones_like(s), s, s * s, s * s * s]
    return np.stack([powers[i][:, 0] * powers[j][:, 1] * powers[k][:, 2] for i, j, k in EXPONENTS.astype(int)], 1)


def _robust_fit(x, y, prior=None, pull=1e-4):
    """Least squares x @ coef = y that ignores outliers and is pulled towards
    `prior` (ridge regression), so unseen colours keep a sensible answer."""
    prior = np.zeros((x.shape[1], y.shape[1]), np.float32) if prior is None else prior
    ridge = pull * len(x) * np.eye(x.shape[1], dtype=np.float32)
    weight = np.ones(len(x), np.float32)
    for _ in range(3):
        xw = x * weight[:, None]
        coef = np.linalg.solve(xw.T @ x + ridge, xw.T @ y + ridge @ prior)
        error = np.abs(x @ coef - y).max(1)
        weight = (error < 3 * (1.4826 * np.median(error) + 1)).astype(np.float32)
    return coef.astype(np.float32)


class Predictor:
    def __init__(self, cam_to_screen, screen_size, camera_size, scale=0.5):
        """cam_to_screen: homography from calibration. Sizes are (width, height).
        `scale` shrinks the camera region we work in (0.5 = half resolution)."""
        w, h = screen_size
        screen_to_cam = np.linalg.inv(cam_to_screen)
        quad = cv2.perspectiveTransform(np.float32([[[0, 0], [w, 0], [w, h], [0, h]]]), screen_to_cam)[0]
        x0, y0 = np.maximum(np.floor(quad.min(0)).astype(int) - 8, 0)
        x1, y1 = np.minimum(np.ceil(quad.max(0)).astype(int) + 8, camera_size)
        self.roi = (slice(y0, y1), slice(x0, x1))
        self.size = (int((x1 - x0) * scale), int((y1 - y0) * scale))  # working image (width, height)
        cam_to_work = np.diag([self.size[0] / (x1 - x0), self.size[1] / (y1 - y0), 1.0]) @ np.float64([[1, 0, -x0], [0, 1, -y0], [0, 0, 1]])
        self.cam_to_screen, self.work_to_cam = cam_to_screen, np.linalg.inv(cam_to_work)
        self.screen_to_work = cam_to_work @ screen_to_cam  # full-resolution screen pixels -> working pixels
        self.span = float(np.linalg.norm(quad[1] - quad[0]))  # width of the projected picture in camera pixels
        self._small_to_work = self.screen_to_work @ np.diag([1 / SCREEN_SCALE, 1 / SCREEN_SCALE, 1.0])
        small = (int(w * SCREEN_SCALE), int(h * SCREEN_SCALE))
        inside = cv2.warpPerspective(np.full(small[::-1], 255, np.uint8), self._small_to_work, self.size)
        self.inside = cv2.erode(inside, np.ones((5, 5), np.uint8)) > 0
        self.colour_map = None  # 20 polynomial terms x 3 camera channels, from calibration
        self._cached_screen = None

    def warp_screen(self, screen_small):
        """Half-resolution screen picture -> working view, as the camera would frame it."""
        return cv2.warpPerspective(screen_small, self._small_to_work, self.size, borderMode=cv2.BORDER_REPLICATE)

    def crop_camera(self, frame):
        return cv2.resize(frame[self.roi], self.size, interpolation=cv2.INTER_AREA).astype(np.float32)

    def calibrate_colour(self, pairs):
        """Fit the colour map from (screen_small, camera frame) pairs of the
        colour-mosaic patterns. Pixels near tile borders are left out."""
        xs, ys = [], []
        kernel = np.ones((7, 7), np.uint8)
        for screen_small, frame in pairs:
            warped, observed = self.warp_screen(screen_small), self.crop_camera(frame)
            flat = (cv2.dilate(warped, kernel).astype(int) - cv2.erode(warped, kernel)).max(2) < 6
            keep = (flat & self.inside & (observed.max(2) < 250))[::2, ::2].ravel()
            xs.append(_features(warped[::2, ::2].reshape(-1, 3)[keep]))
            ys.append(observed[::2, ::2].reshape(-1, 3)[keep])
        self.colour_map = _robust_fit(np.concatenate(xs), np.concatenate(ys), pull=CALIBRATION_PULL)
        self._cached_screen = None

    def _terms(self, screen_small):
        """Polynomial terms of the warped screen picture. Cached, because the
        screen is usually static between frames."""
        if self._cached_screen is not screen_small:
            warped = self.warp_screen(screen_small)
            self._cached_terms = _features(warped.reshape(-1, 3))
            # Flat areas: only these are used for fitting, because at edges a
            # one-pixel misalignment looks like a big colour error.
            kernel = np.ones((5, 5), np.uint8)
            self._cached_flat = cv2.subtract(cv2.dilate(warped, kernel), cv2.erode(warped, kernel)).max(2) < 24
            # How much each pixel would change if the projector colours changed
            # strength: banding hits saturated colours hardest, so they get more slack.
            self._cached_slack = BAND_SLACK * sum(np.abs(self._cached_terms @ (EXPONENTS[:, k:k + 1] * self.colour_map)) for k in range(3)).reshape(warped.shape)
            self._cached_screen = screen_small
        return self._cached_terms, self._cached_flat, self._cached_slack

    def _adapt(self, terms, observed, usable, step=4):
        """Today's colour map: the calibrated one, first moved by a colour
        matrix to the camera's current exposure, then refitted on the colours
        that are on screen now. Colours not on screen keep the calibrated shape."""
        h, w = observed.shape[:2]
        sub = np.zeros((h, w), bool)
        sub[step // 2::step, step // 2::step] = True
        keep = (sub & usable).ravel()
        if keep.sum() < 200:
            return self.colour_map
        x, y = terms[keep], observed.reshape(-1, 3)[keep]
        # Exposure: a 3x3 colour matrix plus offset, pulled towards "no change".
        # It is fitted afresh every frame; carrying it over lets it drift in
        # directions that a plain-coloured screen cannot pin down.
        base = np.hstack([x @ self.colour_map / 255, np.ones((len(x), 1), np.float32)])
        exposure = _robust_fit(base, y / 255, NO_CHANGE, pull=0.02)
        prior = self.colour_map @ exposure[:3]
        prior[0] += exposure[3] * 255  # term 0 is the constant
        return _robust_fit(x, y, prior, pull=0.01)

    def _row_strengths(self, error, slopes, usable, step=3):
        """Per camera row, the change in strength of the three projector colours
        that best explains the leftover error (least squares, 3 unknowns per
        row, estimated from every third pixel). Rows without enough trusted
        pixels borrow from their neighbours. Returns the correction to add to
        the prediction."""
        h, w = usable.shape
        error, trusted = error[:, ::step], usable[:, ::step].copy()
        s = slopes[:, ::step].reshape(h, -1, 3)  # per row: one equation per pixel and channel
        e = error.reshape(h, -1, 1)
        trusted &= cv2.absdiff(error, 0.0).max(2) < 60
        for limit in (None, 25):  # second pass: drop what the first pass could not explain
            if limit:
                trusted &= cv2.absdiff(error, (s @ delta[..., None]).reshape(error.shape)).max(2) < limit
            weighted = (s * np.repeat(trusted, 3, axis=1)[..., None]).transpose(0, 2, 1)
            normal = weighted @ s
            normal += (ROW_RIDGE * np.trace(normal, axis1=1, axis2=2)[:, None, None] + 1e-3) * np.eye(3, dtype=np.float32)
            delta = np.clip(np.linalg.solve(normal, weighted @ e)[..., 0], -ROW_LIMIT, ROW_LIMIT)
            good = trusted.sum(1) > 10
            if good.any():
                rows = np.arange(h)
                delta = np.stack([np.interp(rows, rows[good], delta[good, k]) for k in range(3)], 1)
            delta = cv2.blur(delta.astype(np.float32), (1, 5))
        return (slopes.reshape(h, -1, 3) @ delta[..., None]).reshape(h, w, 3)

    def residual(self, screen_small, frame, skip=None):
        """How strongly each working pixel disagrees with the prediction, in
        grey levels. `skip` marks working pixels to leave out (screen content
        in motion). Returns (residual, predicted, observed)."""
        observed = self.crop_camera(frame)
        terms, flat, band_slack = self._terms(screen_small)
        usable = self.inside & flat if skip is None else self.inside & flat & ~skip
        colour_map = self._adapt(terms, observed, usable)
        predicted = (terms @ colour_map).reshape(observed.shape)
        # d(prediction) / d(log strength of projector colour k): scaling screen
        # colour k scales each polynomial term by its power of k.
        slopes = np.stack([(terms @ (EXPONENTS[:, k:k + 1] * colour_map)).reshape(observed.shape) for k in range(3)], -1)
        predicted += self._row_strengths(observed - predicted, slopes, usable)
        # Smooth leftover brightness drift (uneven screen, lens glare) on a coarse grid.
        half = (slice(None, None, 2), slice(None, None, 2))
        ratio = np.where(usable[half], observed[half].sum(2) / np.maximum(predicted[half].sum(2), 1), np.nan).astype(np.float32)
        gy, gx = 5, 8
        hh, ww = ratio.shape[0] // gy * gy, ratio.shape[1] // gx * gx
        with np.errstate(all="ignore"):
            grid = np.nanmedian(ratio[:hh, :ww].reshape(gy, hh // gy, gx, ww // gx), axis=(1, 3))
        grid = np.where(np.isnan(grid), 1.0, np.clip(grid, 0.8, 1.25)).astype(np.float32)
        predicted *= cv2.resize(grid, self.size, interpolation=cv2.INTER_CUBIC)[..., None]
        # Tolerance for misalignment and camera sharpening: compare against the
        # local min..max of the prediction, widened by a quarter of that range.
        np.clip(predicted, 0, 255, out=predicted)  # the camera cannot report more than white
        kernel = np.ones((5, 5), np.uint8)
        low, high = cv2.erode(predicted, kernel), cv2.dilate(predicted, kernel)
        slack = 0.25 * (high - low) + band_slack
        residual = np.maximum(np.maximum(observed - high - slack, low - slack - observed), 0).max(2)
        residual[~self.inside] = 0
        if skip is not None:
            residual[skip] = 0
        return residual, predicted, observed
