"""Turns per-frame hand detections into steady pointers with clicks and swipes.

Each pointer has a constant-velocity Kalman filter: it smooths the jittery
fingertip and, because it knows the velocity, can report where the finger is
now rather than where the camera saw it a moment ago.
"""
from collections import deque

import numpy as np

LEAD = 0.06  # seconds of motion to predict ahead, to offset camera delay
LOST_AFTER = 0.3  # seconds without a detection before a pointer is dropped
CONFIRM = 3  # detections in a row before a pointer is reported (false blobs flicker)
MATCH_RADIUS = 0.25  # a detection this far (fraction of screen width) from a pointer is a new hand
DWELL_RADIUS, DWELL_TIME, TAP_TIME = 0.025, 0.8, 0.15  # hold still this long to click
SWIPE_DISTANCE, SWIPE_TIME, SWIPE_COOLDOWN = 0.3, 0.5, 1.0


class Kalman:
    """State (x, y, vx, vy); we measure (x, y)."""

    def __init__(self, position, noise=0.004, agility=3.0):
        self.state = np.array([*position, 0.0, 0.0])
        self.cov = np.diag([noise ** 2, noise ** 2, 1.0, 1.0])
        self.noise, self.agility = noise, agility  # measurement jitter; expected acceleration

    def update(self, position, dt):
        f = np.eye(4)
        f[0, 2] = f[1, 3] = dt
        q = self.agility ** 2 * np.diag([dt ** 4 / 4, dt ** 4 / 4, dt ** 2, dt ** 2])
        self.state = f @ self.state
        self.cov = f @ self.cov @ f.T + q
        gain = self.cov[:, :2] @ np.linalg.inv(self.cov[:2, :2] + np.eye(2) * self.noise ** 2)
        self.state = self.state + gain @ (np.asarray(position) - self.state[:2])
        self.cov = self.cov - gain @ self.cov[:2]

    def ahead(self, seconds):
        return self.state[:2] + self.state[2:] * seconds


class Pointer:
    def __init__(self, number, position, now):
        self.id, self.filter, self.seen, self.hits = number, Kalman(position), now, 0
        self.pose, self.down, self.candidate, self.pending = "point", False, "point", 0
        self.anchor, self.anchor_time, self.tap_until, self.armed, self.held = np.array(position), now, 0.0, True, False
        self.trail = deque()  # (time, x) for swipe detection


class Tracker:
    def __init__(self, dwell=True):
        self.pointers, self.dwell = [], dwell
        # What holding still does. False: one short tap (buttons). True: press
        # and stay pressed until the next hold (drawing without a pinch).
        self.hold = False
        self._next_id, self._swipe_ready = 1, 0.0

    def update(self, detections, now):
        """detections: list of {"pos": (x, y) in 0..1, "pose": str or None}.
        Returns (pointers for the protocol, list of gesture names)."""
        free = list(self.pointers)
        for det in detections:
            position = np.asarray(det["pos"], float)
            near = min(free, key=lambda p: np.linalg.norm(p.filter.state[:2] - position), default=None)
            if near is not None and np.linalg.norm(near.filter.state[:2] - position) < MATCH_RADIUS:
                free.remove(near)
                near.filter.update(position, max(now - near.seen, 1e-3))
            else:
                near = Pointer(self._next_id, position, now)
                self._next_id += 1
                self.pointers.append(near)
            pose = det.get("pose") or "point"
            # A pose must repeat before it replaces the old one: landmark poses flicker.
            near.pending = near.pending + 1 if pose == near.candidate else 1
            near.candidate = pose
            if near.pending >= 2:
                near.pose = pose
            near.seen, near.hits = now, near.hits + 1
        # Drop pointers that vanished, and unconfirmed ones the moment they miss a frame.
        self.pointers = [p for p in self.pointers if now - p.seen < (LOST_AFTER if p.hits >= CONFIRM else 1e-6)]

        gestures = []
        for p in self.pointers:
            position = p.filter.ahead(LEAD)
            # Dwell click: holding the pointing finger still gives one short tap.
            if np.linalg.norm(position - p.anchor) > DWELL_RADIUS:
                p.anchor, p.anchor_time, p.armed = position.copy(), now, True
            elif self.dwell and p.armed and p.pose == "point" and now - p.anchor_time > DWELL_TIME:
                p.armed = False
                if self.hold:
                    p.held = not p.held
                else:
                    p.tap_until = now + TAP_TIME
            p.down = p.pose == "pinch" or now < p.tap_until or (self.hold and p.held)
            # Swipe: a fast, long, sideways move.
            p.trail.append((now, position[0]))
            while now - p.trail[0][0] > SWIPE_TIME:
                p.trail.popleft()
            travel = position[0] - p.trail[0][1]
            if abs(travel) > SWIPE_DISTANCE and now > self._swipe_ready and not p.down:
                gestures.append("swipe_right" if travel > 0 else "swipe_left")
                self._swipe_ready = now + SWIPE_COOLDOWN
                p.trail.clear()
                p.trail.append((now, position[0]))
        out = [{"id": p.id, "x": round(float(np.clip(p.filter.ahead(LEAD)[0], 0, 1)), 4),
                "y": round(float(np.clip(p.filter.ahead(LEAD)[1], 0, 1)), 4), "down": bool(p.down), "pose": p.pose}
               for p in self.pointers if now - p.seen < 0.1 and p.hits >= CONFIRM]
        return out, gestures


if __name__ == "__main__":  # self-check
    tracker, rng = Tracker(), np.random.default_rng(0)
    # A finger moving right at 0.3 screen widths per second with jitter.
    errors = []
    for i in range(60):
        t = i / 30
        truth = np.array([0.2 + 0.3 * t, 0.5])
        out, _ = tracker.update([{"pos": truth + rng.normal(0, 0.004, 2)}], t)
        if i > 15:
            errors.append(abs(out[0]["x"] - (truth[0] + 0.3 * LEAD)))
    assert np.mean(errors) < 0.01, np.mean(errors)
    assert out[0]["id"] == 1 and not out[0]["down"]
    # Holding still produces exactly one tap.
    downs = [tracker.update([{"pos": (0.5, 0.5)}], 2 + i / 30)[0][0]["down"] for i in range(90)]
    assert sum(np.diff(np.array(downs, int)) == 1) == 1, downs
    # A pinch is down immediately; a second hand gets a new id; a fast sweep is a swipe.
    out, _ = tracker.update([{"pos": (0.5, 0.5), "pose": "pinch"}, {"pos": (0.1, 0.9)}], 5.1)
    assert len(out) == 1 and not out[0]["down"], out  # one pinch frame could be a flicker
    out, _ = tracker.update([{"pos": (0.5, 0.5), "pose": "pinch"}, {"pos": (0.1, 0.9)}], 5.12)
    assert len(out) == 1 and out[0]["down"], out  # the new hand is not reported until confirmed
    for i in range(3):
        out, _ = tracker.update([{"pos": (0.5, 0.5), "pose": "pinch"}, {"pos": (0.1, 0.9)}], 5.13 + i / 30)
    assert len(out) == 2 and out[0]["id"] != out[1]["id"] and not out[1]["down"], out
    tracker = Tracker()
    names = [g for i in range(14) for g in tracker.update([{"pos": (0.1 + 0.05 * i, 0.5), "pose": "palm"}], 10 + i / 30)[1]]
    assert names == ["swipe_right"], names
    # Hold mode: the first hold presses, moving keeps it pressed, the next hold releases.
    tracker = Tracker()
    tracker.hold = True
    path = [(0.3, 0.5)] * 30 + [(0.3 + 0.01 * i, 0.5) for i in range(30)] + [(0.6, 0.5)] * 30
    downs = [tracker.update([{"pos": pos}], 20 + i / 30)[0] for i, pos in enumerate(path)]
    downs = [d[0]["down"] for d in downs if d]
    assert not downs[0] and downs[40] and not downs[-1], downs
    print("ok")
