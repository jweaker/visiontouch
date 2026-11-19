"""Draws every figure from the recorded data, results.json and the rig reports.

    uv run python -m eval.experiments     # first, to (re)compute results.json
    uv run python -m eval.figures

Writes runs/figures/*.png and mirrors them to docs/figures/ (runs/ is not
committed, the docs need their pictures). Light backgrounds and large type:
the figures are meant to be projected.
"""
import json
import shutil
from pathlib import Path

import cv2
import matplotlib

matplotlib.use("Agg")  # files only, never a window
import matplotlib.pyplot as plt
import numpy as np

from eval import experiments as ex

OUT, MIRROR = ex.OUT, Path("docs/figures")
CAM_COLOUR = {"0": "#2a78d6", "android": "#eb6834"}
CAM_LABEL = {"0": "Webcam", "android": "Phone"}
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
plt.rcParams.update({
    "font.size": 17, "axes.titlesize": 20, "axes.labelsize": 18, "xtick.labelsize": 15, "ytick.labelsize": 15,
    "legend.fontsize": 15, "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
    "axes.edgecolor": MUTED, "axes.labelcolor": INK, "text.color": INK, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 1, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False, "font.family": "DejaVu Sans",
})
SIZE = (16, 9)  # inches; saved at 120 dpi = 1920 x 1080


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.png", dpi=120, bbox_inches="tight", pad_inches=0.25)
    plt.close(fig)
    print("wrote", OUT / f"{name}.png")


def rgb(image):
    return cv2.cvtColor(np.clip(image, 0, 255).astype(np.uint8), cv2.COLOR_BGR2RGB)


def image_panel(ax, image, title, cmap=None):
    ax.imshow(image, cmap=cmap)
    ax.set_title(title, loc="left")
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)


def pct(v):
    return 100 * v if v is not None else np.nan


# --- pipeline strips ---

def pipeline_strip(results, cam, picture, kind, name, headline):
    p = ex.predictor(cam)
    folder = ex.ROOT / f"{picture}__{kind}"
    screen = ex.small(cv2.imread(str(ex.ROOT / f"{picture}__clean" / "screen.png")))
    frame = cv2.imread(str(folder / f"{cam}_1.jpg"))
    truth = cv2.warpPerspective(cv2.imread(str(folder / "mask.png"), 0), p.screen_to_work, p.size) > 128
    true_tip = cv2.perspectiveTransform(np.float32([[json.loads((ex.ROOT / "index.json").read_text())[f"{picture}__{kind}"]["tip"]]]), p.screen_to_work)[0, 0]
    residual, predicted, observed = p.residual(screen, frame)
    mask, hand, _ = ex.detect(residual, p, truth & p.inside)
    fig, axes = plt.subplots(2, 3, figsize=SIZE)
    image_panel(axes[0, 0], rgb(observed), "1  Camera frame (cropped)")
    image_panel(axes[0, 1], rgb(p.warp_screen(screen)), "2  Screenshot, warped to camera view")
    image_panel(axes[0, 2], rgb(predicted), "3  Predicted camera image")
    image_panel(axes[1, 0], np.minimum(residual, 40), "4  Residual (grey levels)", cmap="magma")
    fig.colorbar(axes[1, 0].images[0], ax=axes[1, 0], fraction=0.035, pad=0.02)
    image_panel(axes[1, 1], mask, "5  Mask after threshold + morphology", cmap="gray")
    overlay = rgb(observed)
    overlay[mask] = (overlay[mask] * 0.5 + np.array([40, 160, 80]) * 0.5).astype(np.uint8)
    image_panel(axes[1, 2], overlay, "6  Fingertip")
    axes[1, 2].plot(*true_tip, "o", ms=16, mfc="none", mec="white", mew=3, label="true tip")
    if hand is not None:
        axes[1, 2].plot(*hand["tip"], "x", ms=16, mew=4, color="#e34948", label="found tip")
        axes[1, 2].plot(*hand["entry"], "s", ms=10, color="#eda100", label="arm enters")
    axes[1, 2].legend(loc="lower right", framealpha=0.9, fontsize=13)
    pic = results["cameras"][cam]["per_picture"][picture]
    fig.suptitle(f"{headline}: '{picture}', {CAM_LABEL[cam].lower()} camera, synthetic {kind}. "
                 f"Clean-frame false positives {pct(pic['clean_mask_fp']):.1f} %, median tip error "
                 f"{pic['tip_median_px']:.0f} px" if pic["tip_median_px"] is not None else f"{headline}: '{picture}'",
                 fontsize=18, x=0.01, ha="left")
    fig.tight_layout()
    save(fig, name)


def pipeline_strips(results):
    per = results["cameras"]["0"]["per_picture"]
    easy = [n for n, v in per.items() if v["class"] in ("slides and text", "drawings and games") and v["tip_median_px"] is not None]
    good = min(easy, key=lambda n: per[n]["tip_median_px"])
    hard = [n for n, v in per.items() if v["class"] == "photos and desktop"]
    bad = max(hard, key=lambda n: per[n]["clean_mask_fp"])
    pipeline_strip(results, "0", good, "hand", "pipeline_good", "Good case")
    pipeline_strip(results, "0", bad, "hand", "pipeline_failure", "Failure case")


# --- banding ---

def banding(results):
    """The plain picture and camera where row correction removes the most residual."""
    best = None
    for cam in ex.CAMERAS:
        p = ex.predictor(cam)
        for picture in ("white", "light", "pastel", "red", "green", "mid"):
            screen = ex.small(cv2.imread(str(ex.ROOT / f"{picture}__clean" / "screen.png")))
            frame = cv2.imread(str(ex.ROOT / f"{picture}__clean" / f"{cam}_1.jpg"))
            before, predicted, observed = ex.residual_at(p, screen, frame, 2)
            after = ex.residual_at(p, screen, frame, 3)[0]
            gain = before[p.inside].mean() - after[p.inside].mean()
            if best is None or gain > best[0]:
                best = (gain, cam, picture, observed, before, after, p.inside)
    _, cam, picture, observed, before, after, inside = best
    fig = plt.figure(figsize=SIZE)
    grid = fig.add_gridspec(2, 3, width_ratios=[1, 1, 0.8])
    image_panel(fig.add_subplot(grid[0, 0]), rgb(observed), "Camera sees a plain picture")
    top = max(np.percentile(before[inside], 99), 10)
    image_panel(fig.add_subplot(grid[0, 1]), np.minimum(before, top), "Residual before row correction", cmap="magma")
    image_panel(fig.add_subplot(grid[1, 1]), np.minimum(after, top), "Residual after row correction", cmap="magma")
    ax = fig.add_subplot(grid[:, 2])
    rows = np.arange(before.shape[0])
    def mean_row(r):  # rows outside the picture have no pixels: left blank
        counts = inside.sum(1)
        return np.where(counts > 0, (r * inside).sum(1) / np.maximum(counts, 1), np.nan)
    ax.plot(mean_row(before), rows, color=SERIES[1], lw=2, label="before")
    ax.plot(mean_row(after), rows, color=SERIES[0], lw=2, label="after")
    ax.invert_yaxis()
    ax.set_xlabel("mean residual in the row (grey levels)")
    ax.set_ylabel("camera row")
    ax.legend(loc="lower right")
    ax.set_title("Per row", loc="left")
    fig.add_subplot(grid[1, 0]).axis("off")
    fig.text(0.04, 0.25, f"'{picture}' picture, {CAM_LABEL[cam].lower()} camera.\nMean residual inside the picture:\n"
             f"{before[inside].mean():.1f} grey levels before,\n{after[inside].mean():.1f} after.\n\n"
             "The projector shows red, green and blue\none after another; the camera reads its\nrows one after another, so each row\ncatches a different colour mix.",
             fontsize=16, va="center")
    fig.suptitle("Rainbow banding and the per-row correction", x=0.01, ha="left")
    fig.tight_layout()
    save(fig, "banding")


# --- ablation, ROC, sweep ---

def ablation(results):
    labels = results["variants"]
    short = ["(a) plain\nsubtraction", "(b) + colour\nmap", "(c) + exposure\nadaptation", "(d) + row\nbanding", "(e) + tolerance\n(full method)"]
    metrics = [("clean_mask_fp", "Clean frames: pixels wrongly\nflagged (%), lower is better"),
               ("recall_at_1pct_fp", "Hand pixels found when only 1 %\nof clean pixels may be flagged (%)")]
    fig, axes = plt.subplots(1, 2, figsize=SIZE)
    x = np.arange(len(labels))
    for ax, (key, title) in zip(axes, metrics):
        for i, cam in enumerate(ex.CAMERAS):
            values = [pct(results["cameras"][cam]["ablation"][l][key]) for l in labels]
            bars = ax.bar(x + (i - 0.5) * 0.38, values, 0.36, color=CAM_COLOUR[cam], label=CAM_LABEL[cam] + " camera")
            ax.bar_label(bars, fmt="%.0f", fontsize=13, color=MUTED, padding=2)
        ax.set_xticks(x, short, fontsize=13)
        ax.set_title(title, loc="left", fontsize=18)
        ax.set_ylim(0, 110)
        ax.grid(axis="x", visible=False)
    axes[0].legend(loc="upper right")
    fig.suptitle("Ablation: each step of the method added in turn (all 23 pictures, 3 frames each)", x=0.01, ha="left")
    fig.tight_layout()
    save(fig, "ablation")


def roc(results):
    fig, axes = plt.subplots(1, 2, figsize=SIZE, sharey=True)
    for ax, cam in zip(axes, ex.CAMERAS):
        r = results["cameras"][cam]
        for colour, (label, curve) in zip(SERIES, r["roc"].items()):
            fpr = np.maximum(np.array(curve["fpr"]), 1e-5)
            ax.plot(100 * fpr, 100 * np.array(curve["recall"]), color=colour, lw=2.5 if "full" in label else 2, label=label)
        for key, marker in (("LOW", "o"), ("HIGH", "s")):
            point = r["chosen_thresholds"][key]
            ax.plot(100 * point["fpr"], 100 * point["recall"], marker, ms=12, color=INK, mfc="white", mew=2.5)
            ax.annotate(f"{key} = {point['threshold']}", (100 * point["fpr"], 100 * point["recall"]), xytext=(12, -22),
                        textcoords="offset points", fontsize=14)
        ax.set_xscale("log")
        ax.set_xlim(0.01, 100)
        ax.set_ylim(0, 102)
        ax.set_xlabel("clean pixels flagged (%, log scale)")
        ax.set_title(f"{CAM_LABEL[cam]} camera", loc="left")
    axes[0].set_ylabel("synthetic-hand pixels found (%)")
    axes[1].legend(loc="lower right", fontsize=13)
    fig.suptitle("ROC curves, one pixel at a time, before morphology. Up and left is better.", x=0.01, ha="left")
    fig.tight_layout()
    save(fig, "roc")


def sweep(results):
    fig, axes = plt.subplots(1, 2, figsize=SIZE, sharey=True)
    for ax, (key, title) in zip(axes, [("false_alarm_frames", "Clean frames with a false hand (%)"),
                                       ("hand_found", "Frames where the hand is found (%)")]):
        for cam in ex.CAMERAS:
            s = results["cameras"][cam]["sweep"]
            ax.plot([v["low"] for v in s], [pct(v[key]) for v in s], "o-", color=CAM_COLOUR[cam], lw=2, ms=8, label=CAM_LABEL[cam] + " camera")
        ax.axvline(results["thresholds"]["LOW"], color=MUTED, ls="--", lw=1.5)
        ax.text(results["thresholds"]["LOW"] + 0.3, 3, f"chosen\nLOW={results['thresholds']['LOW']}, HIGH={results['thresholds']['HIGH']}", fontsize=13, color=MUTED)
        ax.set_xlabel("LOW threshold (HIGH scaled with it)")
        ax.set_title(title, loc="left")
        ax.set_ylim(0, 105)
    axes[0].legend(loc="upper right")
    fig.suptitle("Threshold sweep of the full pipeline (one frame at a time, before tracking)", x=0.01, ha="left")
    fig.tight_layout()
    save(fig, "sweep")


# --- per class, per picture ---

def per_class(results):
    classes = list(results["classes"])
    metrics = [("clean_mask_fp", "Clean pixels wrongly flagged (%)"), ("false_alarm_frames", "Clean frames with a false hand (%)"),
               ("hand_recall", "Synthetic-hand pixels found (%)"), ("tip_median_px", "Median fingertip error (px)")]
    fig, axes = plt.subplots(2, 2, figsize=SIZE)
    x = np.arange(len(classes))
    names = [c.replace(" and ", "\nand ") for c in classes]
    for ax, (key, title) in zip(axes.ravel(), metrics):
        for i, cam in enumerate(ex.CAMERAS):
            values = [results["cameras"][cam]["per_class"][c][key] for c in classes]
            values = [np.nan if v is None else (v if key == "tip_median_px" else 100 * v) for v in values]
            bars = ax.bar(x + (i - 0.5) * 0.38, values, 0.36, color=CAM_COLOUR[cam], label=CAM_LABEL[cam] + " camera")
            ax.bar_label(bars, fmt="%.0f", fontsize=12, color=MUTED, padding=2)
        ax.set_xticks(x, names, fontsize=13)
        ax.set_title(title, loc="left", fontsize=17)
        ax.grid(axis="x", visible=False)
        ax.margins(y=0.18)
    axes[0, 0].legend(loc="upper left")
    fig.suptitle("Results by kind of content (full method, dataset ds1)", x=0.01, ha="left")
    fig.tight_layout()
    save(fig, "per_class")


def per_picture(results):
    order = [n for names in results["classes"].values() for n in names if n in results["cameras"]["0"]["per_picture"]]
    fig, axes = plt.subplots(1, 2, figsize=(16, 11), sharey=True)
    y = np.arange(len(order))
    for i, cam in enumerate(ex.CAMERAS):
        per = results["cameras"][cam]["per_picture"]
        axes[0].barh(y + (i - 0.5) * 0.38, [pct(per[n]["clean_mask_fp"]) for n in order], 0.36, color=CAM_COLOUR[cam], label=CAM_LABEL[cam] + " camera")
        tips = [per[n]["tip_median_px"] if per[n]["tip_median_px"] is not None else np.nan for n in order]
        axes[1].barh(y + (i - 0.5) * 0.38, tips, 0.36, color=CAM_COLOUR[cam])
        for yy, v in zip(y, tips):
            if np.isnan(v):
                axes[1].text(1.1, yy + (i - 0.5) * 0.38, "not found", va="center", fontsize=11, color=MUTED)
    axes[0].set_yticks(y, order, fontsize=14)
    axes[0].invert_yaxis()
    axes[0].set_xlabel("clean pixels wrongly flagged (%)")
    axes[1].set_xscale("log")
    axes[1].set_xlim(1, 3000)
    axes[1].axvline(20, color=MUTED, ls="--", lw=1.5)
    axes[1].set_xlabel("median fingertip error (screen px, log scale; dashed = 20 px)")
    fig.legend(*axes[0].get_legend_handles_labels(), loc="upper right")
    start = 0
    for c, names in results["classes"].items():
        start += len([n for n in names if n in order])
        for ax in axes:
            ax.axhline(start - 0.5, color=INK, lw=1)
        axes[0].text(axes[0].get_xlim()[1], start - 0.7, c, ha="right", va="bottom", fontsize=13, color=MUTED)
    for ax in axes:
        ax.grid(axis="y", visible=False)
    fig.suptitle("Every test picture: where the method fails", x=0.01, ha="left")
    fig.tight_layout()
    save(fig, "per_picture")


def fingertip(results):
    fig, ax = plt.subplots(figsize=SIZE)
    for cam in ex.CAMERAS:
        f = results["cameras"][cam]["fingertip"]
        e = np.sort(f["errors_px"])
        ax.step(e, 100 * np.arange(1, len(e) + 1) / f["frames"], where="post", color=CAM_COLOUR[cam], lw=2.5,
                label=f"{CAM_LABEL[cam]} camera: median {f['median_px']:.1f} px ({f['median_pct_width']:.2f} % of width)")
    ax.axvline(20, color=MUTED, ls="--", lw=1.5)
    ax.text(21, 4, "20 px", color=MUTED, fontsize=14)
    ax.set_xscale("log")
    ax.set_xlim(1, 3000)
    ax.set_ylim(0, 100)
    ax.set_xlabel("fingertip error (screen pixels, 1920 wide; log scale)")
    ax.set_ylabel("frames with error at most this (%)")
    ax.legend(loc="upper left")
    ax.set_title("Fingertip error on synthetic hands, cumulative. The curve stops below 100 % at the frames where no hand was found.", loc="left", fontsize=16)
    save(fig, "fingertip")


def calibration(results):
    fig, axes = plt.subplots(1, 2, figsize=SIZE)
    for ax, cam in zip(axes, ex.CAMERAS):
        c = results["calibration"][cam]
        corners, vectors = np.array(c["corners"]), np.array(c["vectors"])
        ax.add_patch(plt.Rectangle((0, 0), ex.W, ex.H, fill=False, ec=MUTED, lw=1.5))
        q = ax.quiver(corners[:, 0], corners[:, 1], vectors[:, 0], vectors[:, 1], color=CAM_COLOUR[cam], angles="xy",
                      scale_units="xy", scale=1 / 40, width=0.003)
        ax.quiverkey(q, 0.75, -0.08, 2, "2 px (arrows 40x longer)", labelpos="E", fontproperties={"size": 13})
        ax.set_xlim(-60, ex.W + 60)
        ax.set_ylim(ex.H + 60, -60)
        ax.set_aspect("equal")
        ax.set_title(f"{CAM_LABEL[cam]}: {c['markers']} of {c['markers_total']} markers, RMS {c['rms_px']:.2f} px", loc="left", fontsize=17)
        ax.set_xticks([0, 960, 1920])
        ax.set_yticks([0, 540, 1080])
    fig.suptitle("Geometric calibration: where each marker corner lands after the homography, minus where it should be", x=0.01, ha="left", fontsize=18)
    fig.tight_layout()
    save(fig, "calibration")


# --- rig reports ---

def keystone(rig):
    report = rig["keystone"].get("0")
    plain, corrected = Path("runs/keystone/plain_0.jpg"), Path("runs/keystone/corrected_0.jpg")
    if report is None or not plain.exists() or not corrected.exists():
        print("skip keystone: no report or photos")
        return
    fig, axes = plt.subplots(1, 2, figsize=(16, 5.6))
    for ax, path, key, word in ((axes[0], plain, "plain", "Before"), (axes[1], corrected, "corrected", "After")):
        r = report[key]
        image_panel(ax, cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB),
                    f"{word}: edges tilted {r['tilt_degrees']:.2f}°, aspect {r['aspect']:.2f}")
    fig.suptitle(f"Keystone correction, webcam photos (target aspect {16 / 9:.2f}). "
                 f"Pointer error in the corrected picture: median {report['pointer_error_px']['median']:.1f} px", x=0.01, ha="left", fontsize=17)
    fig.tight_layout()
    save(fig, "keystone")


def report_colour(key):
    """Webcam blue, phone orange; other conditions (e.g. washed-out) take the next slots."""
    return CAM_COLOUR.get(key) or SERIES[2 + sorted(k for k in ex.rig_reports()["live"] if k not in CAM_COLOUR).index(key) % 3]


def latency(rig, results):
    keys = list(rig["live"])
    if not keys:
        print("skip latency: no live reports")
        return
    fig, axes = plt.subplots(1, len(keys), figsize=(16, 6), squeeze=False)
    for ax, key in zip(axes[0], keys):
        report = rig["live"][key]
        offline = results["cameras"].get(key, {}).get("ms_per_frame_residual")
        rows = [("camera + projector delay\n(measured at calibration)", report["camera_delay_ms"]),
                ("engine step, live\n(median per frame)", report["ms_per_frame"]),
                ("residual only, offline\n(median per frame)", offline)]
        rows = [r for r in rows if r[1] is not None]
        bars = ax.barh(range(len(rows)), [r[1] for r in rows], color=report_colour(key), height=0.6)
        ax.bar_label(bars, fmt="%.0f ms", padding=4, fontsize=15)
        ax.set_yticks(range(len(rows)), [r[0] for r in rows], fontsize=13)
        ax.invert_yaxis()
        ax.set_xlim(0, max(r[1] for r in rows) * 1.3)
        ax.set_xlabel("milliseconds")
        ax.set_title(report["label"], loc="left", fontsize=16)
        ax.grid(axis="y", visible=False)
    fig.suptitle("Where the time goes", x=0.01, ha="left")
    fig.tight_layout()
    save(fig, "latency")


def live(rig):
    keys = list(rig["live"])
    if not keys:
        return
    names = list(dict.fromkeys(r["picture"] for k in keys for r in rig["live"][k]["pictures"]))
    fig, axes = plt.subplots(1, 2, figsize=SIZE, sharey=True)
    y = np.arange(len(names))
    width = 0.8 / len(keys)
    for i, key in enumerate(keys):
        rows = {r["picture"]: r for r in rig["live"][key]["pictures"]}
        found = [100 * np.mean([rows[n][k]["found"] for k in ("shadow", "hand")]) if n in rows else np.nan for n in names]
        error = [np.nanmedian([rows[n][k]["median_error_px"] if rows[n][k]["median_error_px"] is not None else np.nan for k in ("shadow", "hand")])
                 if n in rows else np.nan for n in names]
        offset = (i - (len(keys) - 1) / 2) * width
        axes[0].barh(y + offset, found, width * 0.95, color=report_colour(key), label=rig["live"][key]["label"])
        axes[1].barh(y + offset, error, width * 0.95, color=report_colour(key))
    axes[0].set_yticks(y, names)
    axes[0].invert_yaxis()
    axes[0].set_xlim(0, 100)
    axes[0].set_xlabel("frames with a pointer (%)")
    axes[1].set_xscale("log")
    axes[1].set_xlabel("median pointer error (screen px, log scale)")
    axes[1].axvline(20, color=MUTED, ls="--", lw=1.5)
    fig.legend(*axes[0].get_legend_handles_labels(), loc="lower center", ncol=len(keys), bbox_to_anchor=(0.5, -0.04))
    alarms = max(r["false_alarm_frames"] for k in keys for r in rig["live"][k]["pictures"])
    fig.suptitle("Live rig: synthetic hands through the real projector (mean of shadow and lit hand).\n"
                 f"Clean pictures, nobody present: at most {100 * alarms:.0f} % of frames had a false hand.", x=0.01, ha="left", fontsize=17)
    for ax in axes:
        ax.grid(axis="y", visible=False)
    fig.tight_layout()
    save(fig, "live")


def idle(rig):
    cams = [c for c in ex.CAMERAS if c in rig["idle"]]
    if not cams:
        return
    apps = list(rig["idle"][cams[0]])
    fig, ax = plt.subplots(figsize=(16, 7))
    x = np.arange(len(apps))
    for i, cam in enumerate(cams):
        r = rig["idle"][cam]
        values = [100 * r[a]["false_alarm_frames"] / max(r[a]["frames"], 1) if a in r else np.nan for a in apps]
        bars = ax.bar(x + (i - 0.5) * 0.38, values, 0.36, color=CAM_COLOUR[cam], label=CAM_LABEL[cam] + " camera")
        ax.bar_label(bars, fmt="%.0f", fontsize=13, color=MUTED, padding=2)
    ax.set_xticks(x, apps)
    ax.set_ylabel("frames with a false hand (%)")
    ax.set_ylim(0, 100)
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper left")
    ax.set_title("Nobody in front of the screen: false alarms per app (about 4 s per app, pointers after tracking)", loc="left", fontsize=17)
    save(fig, "idle")


def mediapipe(results):
    m = results.get("mediapipe")
    if not m:
        print("skip mediapipe: not in results.json")
        return
    keys = [("clean_full", "clean frame,\nwhole image"), ("hand_full", "synthetic hand,\nwhole image"),
            ("hand_engine_crop", "synthetic hand,\nengine's crop"), ("hand_true_crop", "synthetic hand,\ncrop at true tip")]
    fig, ax = plt.subplots(figsize=(16, 7))
    x = np.arange(len(keys))
    for i, cam in enumerate(ex.CAMERAS):
        bars = ax.bar(x + (i - 0.5) * 0.38, [pct(m[cam][k]["rate"]) for k, _ in keys], 0.36, color=CAM_COLOUR[cam], label=CAM_LABEL[cam] + " camera")
        ax.bar_label(bars, labels=[f"{m[cam][k]['fired']}/{m[cam][k]['frames']}" for k, _ in keys], fontsize=13, color=MUTED, padding=2)
    ax.set_xticks(x, [k[1] for k in keys])
    ax.set_ylim(0, 100)
    ax.set_ylabel("frames where MediaPipe reports a hand (%)")
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper right")
    ax.set_title("MediaPipe Hands on the synthetic hands: they are flat paintings, not hands, so it rarely fires.\n"
                 "This shows the learned detector cannot replace the classical one here; real hands are tested separately.", loc="left", fontsize=16)
    save(fig, "mediapipe")


def main():
    results = json.loads(ex.RESULTS.read_text())
    rig = ex.rig_reports()
    pipeline_strips(results)
    banding(results)
    ablation(results)
    roc(results)
    sweep(results)
    per_class(results)
    per_picture(results)
    fingertip(results)
    calibration(results)
    mediapipe(results)
    keystone(rig)
    latency(rig, results)
    live(rig)
    idle(rig)
    MIRROR.mkdir(parents=True, exist_ok=True)
    for path in OUT.glob("*.png"):
        shutil.copy(path, MIRROR / path.name)
    print(f"mirrored to {MIRROR}")


if __name__ == "__main__":
    main()
