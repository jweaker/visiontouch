"""Offline experiments on the recorded dataset. Writes runs/figures/results.json.

    uv run python -m eval.experiments            # everything (about two minutes)
    uv run python -m eval.experiments --no-mediapipe

Data: runs/ds1 (test pictures, clean and with synthetic hands, two cameras) and
runs/ds1b (calibration captures). Nothing here opens a camera or a window.

Experiments, one function each:
  ablation      the method built up step by step, (a) plain subtraction .. (e) full
  sweep         thresholds of the full method: ROC curve and where LOW/HIGH sit
  per picture   results per test picture and per content class (failure cases)
  fingertip     tip localisation error on the synthetic hands
  calibration   marker reprojection error and residual vectors
  mediapipe     how often MediaPipe Hands fires on full frames and on crops
Rig reports (runs/live, runs/idle, runs/keystone) and the real-hand accuracy
log (~/.visiontouch/log.jsonl) are read by `rig_reports` and `real_hands`.
"""
import json
import re
import sys
import time
import warnings
from pathlib import Path

import cv2
import numpy as np

import visiontouch.hands as hands
from visiontouch.calibrate import DICTIONARY, find_homography, marker_pattern
from visiontouch.predict import EXPONENTS, SCREEN_SCALE, Predictor, _robust_fit

warnings.filterwarnings("ignore", "All-NaN slice")  # rows of the drift grid with no usable pixels

ROOT, CAL, OUT = Path("runs/ds1"), Path("runs/ds1b"), Path("runs/figures")
RESULTS = OUT / "results.json"
ACCURACY_LOG = Path.home() / ".visiontouch" / "log.jsonl"
CAMERAS = ("0", "android")
CAMERA_NAMES = {"0": "MacBook webcam (near the projector)", "android": "Phone camera (1.2 m to the side)"}
W, H = 1920, 1080
CLASSES = {
    "plain colours and patterns": ["white", "light", "mid", "dark", "black", "pastel", "red", "green", "ramp", "colour_ramp", "checker"],
    "slides and text": ["slide_light", "slide_dark", "text"],
    "drawings and games": ["board", "balloons"],
    "photos and desktop": ["photo1", "photo2", "photo3", "photo4", "photo5", "photo6", "desktop"],
}
CLASS_OF = {name: c for c, names in CLASSES.items() for name in names}
VARIANTS = {  # level -> label; each level adds one step to the one before
    0: "(a) plain subtraction, global gain",
    1: "(b) + colour map",
    2: "(c) + exposure adaptation",
    3: "(d) + row banding correction",
    4: "(e) + neighbourhood tolerance (full)",
}
SCALES = [0.4, 0.55, 0.7, 0.85, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0]  # threshold sweep: (LOW, HIGH) times this
BINS = np.arange(0, 256.5, 0.5)  # residual histogram bins, grey levels


# --- data ---

def small(image):
    return cv2.resize(image, None, fx=SCREEN_SCALE, fy=SCREEN_SCALE, interpolation=cv2.INTER_AREA)


def predictor(cam):
    """A Predictor calibrated from the ds1b captures, exactly like the engine does."""
    _, corners = marker_pattern(W, H)
    H_, error, count = find_homography(cv2.imread(str(CAL / "cal_markers" / f"{cam}_1.jpg")), corners)
    p = Predictor(H_, (W, H), (W, H))
    p.calibrate_colour([(small(cv2.imread(str(f / "screen.png"))), cv2.imread(str(f / f"{cam}_1.jpg")))
                        for f in sorted(CAL.glob("cal_tiles_*"))])
    return p


def pictures():
    index = json.loads((ROOT / "index.json").read_text())
    return sorted(k[:-7] for k in index if k.endswith("__clean")), index


def frames(cam, p):
    """Every test frame of one camera: dicts with picture, kind, k, screen, frame,
    truth (working-view mask or None) and tip (screen pixels or None)."""
    names, index = pictures()
    for name in names:
        screen = small(cv2.imread(str(ROOT / f"{name}__clean" / "screen.png")))  # the engine is told: no hand
        for kind in ("clean", "shadow", "hand"):
            folder = ROOT / f"{name}__{kind}"
            truth = tip = None
            if kind != "clean":
                truth = cv2.warpPerspective(cv2.imread(str(folder / "mask.png"), 0), p.screen_to_work, p.size) > 128
                truth &= p.inside
                tip = np.array(index[f"{name}__{kind}"]["tip"])
            for k in range(3):
                yield {"picture": name, "kind": kind, "k": k, "screen": screen, "truth": truth, "tip": tip,
                       "frame": cv2.imread(str(folder / f"{cam}_{k}.jpg"))}


def to_screen(p, work_point):
    cam = cv2.perspectiveTransform(np.float32([[work_point]]), p.work_to_cam)
    return cv2.perspectiveTransform(cam, p.cam_to_screen)[0, 0]


# --- the method, one step at a time ---

def _shading(p, observed, predicted, usable):
    """Same as the smooth brightness-drift step in Predictor.residual."""
    half = (slice(None, None, 2), slice(None, None, 2))
    ratio = np.where(usable[half], observed[half].sum(2) / np.maximum(predicted[half].sum(2), 1), np.nan).astype(np.float32)
    gy, gx = 5, 8
    hh, ww = ratio.shape[0] // gy * gy, ratio.shape[1] // gx * gx
    with np.errstate(all="ignore"):
        grid = np.nanmedian(ratio[:hh, :ww].reshape(gy, hh // gy, gx, ww // gx), axis=(1, 3))
    grid = np.where(np.isnan(grid), 1.0, np.clip(grid, 0.8, 1.25)).astype(np.float32)
    return predicted * cv2.resize(grid, p.size, interpolation=cv2.INTER_CUBIC)[..., None]


def residual_at(p, screen, frame, level):
    """Residual of variant `level` (see VARIANTS). Returns (residual, predicted, observed).
    Levels 0-3 compare each pixel with its predicted value directly (absolute
    difference, largest channel); level 4 is Predictor.residual unchanged."""
    if level == 4:
        return p.residual(screen, frame)
    observed = p.crop_camera(frame)
    terms, flat, _ = p._terms(screen)
    usable = p.inside & flat
    if level == 0:
        # One straight line for all colours and channels: camera = gain * screen + offset.
        warped = p.warp_screen(screen).astype(np.float32)
        sub = np.zeros(usable.shape, bool)
        sub[2::4, 2::4] = True
        x, y = warped[sub & usable].reshape(-1, 1), observed[sub & usable].reshape(-1, 1)
        line = _robust_fit(np.hstack([x / 255, np.ones_like(x)]), y, np.float32([[255], [0]]), pull=1e-4)
        predicted = warped / 255 * line[0, 0] + line[1, 0]
    else:
        colour_map = p.colour_map if level == 1 else p._adapt(terms, observed, usable)
        predicted = (terms @ colour_map).reshape(observed.shape)
        if level >= 3:
            slopes = np.stack([(terms @ (EXPONENTS[:, k:k + 1] * colour_map)).reshape(observed.shape) for k in range(3)], -1)
            predicted = _shading(p, observed, predicted + p._row_strengths(observed - predicted, slopes, usable), usable)
    predicted = np.clip(predicted, 0, 255)
    residual = np.abs(observed - predicted).max(2)
    residual[~p.inside] = 0
    return residual, predicted, observed


def detect(residual, p, truth=None):
    """Classical detection on a residual. Returns (mask, hand, number of hands).
    `hand` is the detected hand whose blob covers most of the true hand (None if
    no blob touches it), or the largest one when there is no ground truth. Other
    blobs are extra pointers and are counted as false alarms on clean frames."""
    mask, labels, blobs = hands.clean_mask(residual)
    found = hands.find_tips(labels, blobs, p.inside)
    if truth is None:
        return mask, max(found, key=lambda h: h["area"]) if found else None, len(found)
    overlap = {h["label"]: int((labels[truth] == h["label"]).sum()) for h in found}
    found = [h for h in found if overlap[h["label"]] > 0]
    return mask, max(found, key=lambda h: overlap[h["label"]]) if found else None, len(found)


def _set_thresholds(scale):
    hands.LOW, hands.HIGH = LOW * scale, HIGH * scale


LOW, HIGH = hands.LOW, hands.HIGH


# --- experiments over all frames of one camera ---

def run_camera(cam):
    """One pass over the camera's frames computing every variant. Returns the
    ablation, ROC, threshold sweep, per-picture and fingertip results."""
    p = predictor(cam)
    hist = {lv: {"clean": np.zeros(len(BINS)), "hand": np.zeros(len(BINS))} for lv in VARIANTS}
    abl = {lv: {"clean_pixel_fp": [], "clean_mask_fp": [], "false_alarm": [], "shadow_recall": [], "hand_recall": [],
                "found": [], "tip_error": []} for lv in VARIANTS}
    sweep = {s: {"clean_mask_fp": [], "false_alarm": [], "recall": [], "found": []} for s in SCALES}
    rows, times, checked = {}, [], False
    for f in frames(cam, p):
        row = rows.setdefault(f["picture"], {"class": CLASS_OF.get(f["picture"], "other"), "clean_mask_fp": [], "false_alarm": [],
                                             "shadow_recall": [], "hand_recall": [], "found": [], "tip_error_px": []})
        for level in VARIANTS:
            start = time.perf_counter()
            residual, predicted, observed = residual_at(p, f["screen"], f["frame"], level)
            if level == 4:
                times.append(time.perf_counter() - start)
                if not checked:  # level 3 + tolerance must be exactly the engine's predictor
                    assert np.allclose(residual_at(p, f["screen"], f["frame"], 3)[1], predicted, atol=0.01)
                    checked = True
            values = residual[f["truth"]] if f["truth"] is not None else residual[p.inside]
            hist[level]["hand" if f["truth"] is not None else "clean"] += np.histogram(np.minimum(values, BINS[-1] - 0.01), np.append(BINS, 1e9))[0]
            scales = SCALES if level == 4 else [1.0]
            for s in scales:
                _set_thresholds(s)
                mask, tip, count = detect(residual, p, f["truth"])
                _set_thresholds(1.0)
                if s != 1.0:
                    if f["truth"] is None:
                        sweep[s]["clean_mask_fp"].append(mask[p.inside].mean())
                        sweep[s]["false_alarm"].append(count > 0)
                    else:
                        sweep[s]["recall"].append(mask[f["truth"]].mean())
                        sweep[s]["found"].append(tip is not None)
                    continue
                a = abl[level]
                if f["truth"] is None:
                    a["clean_pixel_fp"].append((residual > LOW)[p.inside].mean())
                    a["clean_mask_fp"].append(mask[p.inside].mean())
                    a["false_alarm"].append(count > 0)
                else:
                    a[f"{f['kind']}_recall"].append(mask[f["truth"]].mean())
                    a["found"].append(tip is not None)
                    error = float(np.linalg.norm(to_screen(p, tip["tip"]) - f["tip"])) if tip else None
                    if error is not None:
                        a["tip_error"].append(error)
                if level == 4:
                    if f["truth"] is None:
                        row["clean_mask_fp"].append(mask[p.inside].mean())
                        row["false_alarm"].append(count > 0)
                    else:
                        row[f"{f['kind']}_recall"].append(mask[f["truth"]].mean())
                        row["found"].append(tip is not None)
                        if error is not None:
                            row["tip_error_px"].append(error)
    mean = lambda v: float(np.mean(v)) if len(v) else None
    ablation = {}
    roc = {}
    for level, label in VARIANTS.items():
        a = abl[level]
        fpr = 1 - np.cumsum(hist[level]["clean"]) / hist[level]["clean"].sum()  # fraction above each bin's upper edge
        tpr = 1 - np.cumsum(hist[level]["hand"]) / hist[level]["hand"].sum()
        thresholds = BINS + 0.5
        at = np.flatnonzero(fpr <= 0.01)
        ablation[label] = {
            "clean_pixel_fp": mean(a["clean_pixel_fp"]), "clean_mask_fp": mean(a["clean_mask_fp"]),
            "false_alarm_frames": mean(a["false_alarm"]), "shadow_recall": mean(a["shadow_recall"]),
            "hand_recall": mean(a["hand_recall"]), "hand_found": mean(a["found"]),
            "tip_median_px": float(np.median(a["tip_error"])) if a["tip_error"] else None,
            "recall_at_1pct_fp": float(tpr[at[0]]) if len(at) else None,
            "threshold_at_1pct_fp": float(thresholds[at[0]]) if len(at) else None,
        }
        keep = np.unique(np.concatenate([np.arange(0, 80, 2), np.arange(80, 512, 16), [len(BINS) - 1]]))
        roc[label] = {"threshold": thresholds[keep].tolist(), "fpr": fpr[keep].tolist(), "recall": tpr[keep].tolist()}
    full = abl[4]
    sweep[1.0] = {"clean_mask_fp": full["clean_mask_fp"], "false_alarm": full["false_alarm"],
                  "recall": full["shadow_recall"] + full["hand_recall"], "found": full["found"]}
    full_hist = hist[4]
    pixel_at = lambda t: {"threshold": t, "fpr": float((full_hist["clean"][BINS >= t]).sum() / full_hist["clean"].sum()),
                          "recall": float((full_hist["hand"][BINS >= t]).sum() / full_hist["hand"].sum())}
    per_picture = {}
    for name, r in rows.items():
        per_picture[name] = {"class": r["class"], "clean_mask_fp": mean(r["clean_mask_fp"]), "false_alarm_frames": mean(r["false_alarm"]),
                             "shadow_recall": mean(r["shadow_recall"]), "hand_recall": mean(r["hand_recall"]),
                             "hand_found": mean(r["found"]), "tip_errors_px": r["tip_error_px"],
                             "tip_median_px": float(np.median(r["tip_error_px"])) if r["tip_error_px"] else None}
    per_class = {}
    for c, names in CLASSES.items():
        rs = [rows[n] for n in names if n in rows]
        errors = [e for r in rs for e in r["tip_error_px"]]
        per_class[c] = {"pictures": [n for n in names if n in rows],
                        "clean_mask_fp": mean([v for r in rs for v in r["clean_mask_fp"]]),
                        "false_alarm_frames": mean([v for r in rs for v in r["false_alarm"]]),
                        "shadow_recall": mean([v for r in rs for v in r["shadow_recall"]]),
                        "hand_recall": mean([v for r in rs for v in r["hand_recall"]]),
                        "hand_found": mean([v for r in rs for v in r["found"]]),
                        "tip_median_px": float(np.median(errors)) if errors else None}
    errors = np.array(full["tip_error"])
    fingertip = {"errors_px": errors.round(2).tolist(), "frames": len(full["found"]), "found_rate": mean(full["found"]),
                 "median_px": float(np.median(errors)), "mean_px": float(errors.mean()), "p90_px": float(np.percentile(errors, 90)),
                 "median_pct_width": float(100 * np.median(errors) / W), "p90_pct_width": float(100 * np.percentile(errors, 90) / W),
                 "within_20px": float(np.mean(errors <= 20)), "within_50px": float(np.mean(errors <= 50))}
    return {
        "frames": {"clean": len(full["false_alarm"]), "with_hand": len(full["found"])},
        "ms_per_frame_residual": 1000 * float(np.median(times)), "working_size": list(p.size),
        "ablation": ablation, "roc": roc,
        "chosen_thresholds": {"LOW": pixel_at(LOW), "HIGH": pixel_at(HIGH)},
        "sweep": [{"scale": s, "low": LOW * s, "high": HIGH * s, "clean_mask_fp": mean(sweep[s]["clean_mask_fp"]),
                   "false_alarm_frames": mean(sweep[s]["false_alarm"]), "recall": mean(sweep[s]["recall"]),
                   "hand_found": mean(sweep[s]["found"])} for s in SCALES],
        "per_picture": per_picture, "per_class": per_class, "fingertip": fingertip,
    }


# --- geometric calibration ---

def marker_residuals(cam, folder=CAL / "cal_markers", k=1, H_=None):
    """Marker corners (screen pixels) and their reprojection error vectors.
    With H_ given, measure that homography instead of fitting a new one."""
    pattern, corners = marker_pattern(W, H)
    image = cv2.imread(str(folder / f"{cam}_{k}.jpg"))
    fitted, rms, count = find_homography(image, corners)
    H_ = fitted if H_ is None else H_
    parameters = cv2.aruco.DetectorParameters()
    parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    found, ids, _ = cv2.aruco.ArucoDetector(DICTIONARY, parameters).detectMarkers(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))
    camera = np.concatenate([c.reshape(4, 2) for c in found])
    screen = np.concatenate([corners[int(i)] for i in ids.ravel()])
    vectors = cv2.perspectiveTransform(camera[None], H_)[0] - screen
    return screen, vectors, rms, count


def calibration():
    out = {}
    for cam in CAMERAS:
        screen, vectors, rms, count = marker_residuals(cam)
        length = np.linalg.norm(vectors, axis=1)
        repeats = [find_homography(cv2.imread(str(CAL / "cal_markers" / f"{cam}_{k}.jpg")), marker_pattern(W, H)[1])[1:] for k in range(3)]
        # The same homography against the marker photo of the other session (ds1): did the camera move?
        H_ = find_homography(cv2.imread(str(CAL / "cal_markers" / f"{cam}_1.jpg")), marker_pattern(W, H)[1])[0]
        other = np.linalg.norm(marker_residuals(cam, ROOT / "cal_markers", 1, H_)[1], axis=1)
        out[cam] = {"markers": count, "markers_total": len(marker_pattern(W, H)[1]), "rms_px": rms,
                    "rms_all_corners_px": float(np.sqrt(np.mean(length ** 2))),
                    "median_px": float(np.median(length)), "max_px": float(length.max()),
                    "rms_pct_width": 100 * rms / W,
                    "repeat_rms_px": [r[0] for r in repeats], "repeat_markers": [r[1] for r in repeats],
                    "other_session_rms_px": float(np.sqrt(np.mean(other ** 2))),
                    "corners": screen.round(1).tolist(), "vectors": vectors.round(3).tolist()}
    return out


# --- classical versus learned ---

def mediapipe_firing():
    """How often MediaPipe Hands reports a hand: on full camera frames, on the
    crop the engine would use (around the classical fingertip) and on a crop
    centred on the true fingertip. Synthetic hands are flat paintings, so this
    only shows how MediaPipe behaves on them, not how well it finds real hands."""
    import mediapipe as mp

    landmarker = hands.Landmarker()
    out = {}
    for cam in CAMERAS:
        p = predictor(cam)
        screen_to_cam = np.linalg.inv(p.cam_to_screen)
        half = 0.13 * p.span
        counts = {key: [] for key in ("clean_full", "hand_full", "hand_engine_crop", "hand_true_crop")}
        errors = []
        for f in frames(cam, p):
            if f["k"] != 1:
                continue
            rgb = np.ascontiguousarray(cv2.cvtColor(f["frame"], cv2.COLOR_BGR2RGB))
            full = landmarker._model.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
            if f["truth"] is None:
                counts["clean_full"].append(bool(full.hand_landmarks))
                continue
            counts["hand_full"].append(bool(full.hand_landmarks))
            residual = residual_at(p, f["screen"], f["frame"], 4)[0]
            tip = detect(residual, p, f["truth"])[1]
            true_tip = cv2.perspectiveTransform(np.float32([[f["tip"]]]), screen_to_cam)[0, 0]
            if tip is not None:
                cam_tip = cv2.perspectiveTransform(np.float32([[tip["tip"]]]), p.work_to_cam)[0, 0]
                arm = cv2.perspectiveTransform(np.float32([[tip["entry"]]]), p.work_to_cam)[0, 0] - cam_tip
                centre = cam_tip + arm / (np.linalg.norm(arm) + 1e-6) * half * 0.5
                points = landmarker.detect(f["frame"], centre, half)
                counts["hand_engine_crop"].append(points is not None)
            else:
                counts["hand_engine_crop"].append(False)
            points = landmarker.detect(f["frame"], true_tip, half)
            counts["hand_true_crop"].append(points is not None)
            if points is not None:
                index_tip = cv2.perspectiveTransform(np.float32([[points[8]]]), p.cam_to_screen)[0, 0]
                errors.append(float(np.linalg.norm(index_tip - f["tip"])))
        out[cam] = {key: {"fired": int(sum(v)), "frames": len(v), "rate": float(np.mean(v)) if v else None} for key, v in counts.items()}
        out[cam]["true_crop_index_tip_error_px"] = errors
    return out


# --- reports from the rig and the real-hand log (read fresh every time) ---

def rig_reports():
    """Every live, idle and keystone report found under runs/."""
    read = lambda path: json.loads(path.read_text())
    out = {"live": {}, "idle": {}, "keystone": {}}
    for kind in out:
        for path in sorted(Path("runs", kind).glob("report_*.json")):
            out[kind][path.stem.removeprefix("report_")] = read(path)
    for report in out["live"].values():
        found = re.search(r"(\d+) ms delay", report.get("calibration", ""))
        report["camera_delay_ms"] = int(found.group(1)) if found else None
    return out


def real_hands(path=ACCURACY_LOG):
    """Accuracy-app taps made with a real hand through the engine (pointer type
    'touch'). Returns None until the log exists and holds such taps."""
    if not path.exists():
        return None
    taps = []
    for line in path.read_text().splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        data = record.get("data") or {}
        if record.get("name") == "accuracy" and data.get("input") == "touch" and "error_px" in data:
            taps.append(data)
    if not taps:
        return None
    errors = np.array([t["error_px"] for t in taps], float)
    pct = np.array([t["error_pct_width"] for t in taps], float)
    return {"taps": len(taps), "sessions": len({t.get("session") for t in taps}),
            "median_error_px": float(np.median(errors)), "mean_error_px": float(errors.mean()),
            "p90_error_px": float(np.percentile(errors, 90)), "median_error_pct_width": float(np.median(pct)),
            "mean_error_pct_width": float(pct.mean()), "max_error_pct_width": float(pct.max()),
            "median_time_s": float(np.median([t["time_ms"] for t in taps]) / 1000),
            "screen_width_px": taps[-1].get("w")}


def main(with_mediapipe=True):
    OUT.mkdir(parents=True, exist_ok=True)
    results = {"generated": time.strftime("%Y-%m-%d %H:%M"), "dataset": str(ROOT), "calibration_data": str(CAL),
               "screen": [W, H], "thresholds": {"LOW": LOW, "HIGH": HIGH, "MIN_AREA": hands.MIN_AREA},
               "classes": CLASSES, "camera_names": CAMERA_NAMES, "variants": list(VARIANTS.values()), "cameras": {}}
    if RESULTS.exists() and not with_mediapipe:
        old = json.loads(RESULTS.read_text())
        if "mediapipe" in old:
            results["mediapipe"] = old["mediapipe"]
    for cam in CAMERAS:
        print(f"camera {cam}: ablation, sweep, per picture, fingertip", flush=True)
        results["cameras"][cam] = run_camera(cam)
    print("calibration", flush=True)
    results["calibration"] = calibration()
    if with_mediapipe:
        print("mediapipe", flush=True)
        results["mediapipe"] = mediapipe_firing()
    RESULTS.write_text(json.dumps(results, indent=1))
    for cam, r in results["cameras"].items():
        print(f"== camera {cam}")
        for label, a in r["ablation"].items():
            print(f"  {label:<40} clean FP {a['clean_mask_fp']:.4f}  false alarms {a['false_alarm_frames']:.2f}  "
                  f"recall shadow {a['shadow_recall']:.2f} hand {a['hand_recall']:.2f}  recall@1%FP {a['recall_at_1pct_fp']}")
        fi = r["fingertip"]
        print(f"  fingertip median {fi['median_px']:.1f} px ({fi['median_pct_width']:.2f} % of width), p90 {fi['p90_px']:.1f} px, found {fi['found_rate']:.2f}")
    print(f"wrote {RESULTS}")


if __name__ == "__main__":
    main(with_mediapipe="--no-mediapipe" not in sys.argv)
