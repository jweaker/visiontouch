"""Keeps the numbers in the documents in sync with the experiments.

    uv run python -m eval.fill_report

Every block between `<!-- BEGIN name -->` and `<!-- END name -->` in
docs/report.md, docs/how-it-works.md and README.md is regenerated from
runs/figures/results.json, the rig reports under runs/ and the real-hand
accuracy log. Text outside the blocks is left alone. Also checks that every
figure the documents link to exists.
"""
import json
import re
import sys
from pathlib import Path

from eval import experiments as ex

DOCUMENTS = [Path("docs/report.md"), Path("docs/how-it-works.md"), Path("README.md")]
CAM = {"0": "Webcam", "android": "Phone"}


def p(v, digits=1):
    """A fraction as a percentage, or a dash."""
    return "–" if v is None else f"{100 * v:.{digits}f} %"


def n(v, digits=1, unit=""):
    return "–" if v is None else f"{v:.{digits}f}{unit}"


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    return "\n".join(out + ["| " + " | ".join(str(c) for c in row) + " |" for row in rows])


def blocks(results, rig, real):
    cams = results["cameras"]
    out = {}
    full = results["variants"][-1]

    # Headline numbers.
    lines = []
    for cam, r in cams.items():
        a, f = r["ablation"][full], r["fingertip"]
        lines.append(f"- **{CAM[cam]} camera, recorded dataset (synthetic hands):** {p(a['clean_mask_fp'])} of clean pixels wrongly flagged "
                     f"(plain subtraction: {p(r['ablation'][results['variants'][0]]['clean_mask_fp'])}); hand found in {p(f['found_rate'], 0)} of frames; "
                     f"median fingertip error {n(f['median_px'])} px ({n(f['median_pct_width'], 2)} % of the screen width).")
    for cam, report in rig["live"].items():
        rows = report["pictures"]
        alarms = max(r["false_alarm_frames"] for r in rows)
        cases = [(r[k]["median_error_px"], r["picture"]) for r in rows for k in ("shadow", "hand") if r[k]["median_error_px"] is not None]
        good = sum(e <= 20 for e, _ in cases)
        worst = max(cases)
        lines.append(f"- **Live rig, {report['label']}:** false-alarm frames on clean pictures at most {p(alarms, 0)}; "
                     f"median pointer error within 20 px in {good} of {len(cases)} picture-and-hand cases; worst {worst[0]:.0f} px on `{worst[1]}`.")
    k = rig["keystone"].get("0")
    if k:
        lines.append(f"- **Keystone (webcam):** edge tilt {k['plain']['tilt_degrees']:.1f}° before, {k['corrected']['tilt_degrees']:.2f}° after; "
                     f"aspect {k['plain']['aspect']:.2f} → {k['corrected']['aspect']:.2f} (target {16 / 9:.2f}).")
    lines.append(f"- **Real hands:** " + (f"median error {n(real['median_error_px'])} px ({n(real['median_error_pct_width'], 2)} % of width) over {real['taps']} taps."
                                           if real else "not yet measured."))
    out["headline"] = "\n".join(lines)

    # Ablation.
    rows = []
    for label in results["variants"]:
        row = [label]
        for cam in cams:
            a = cams[cam]["ablation"][label]
            row += [p(a["clean_mask_fp"]), p(a["false_alarm_frames"], 0), p(a["recall_at_1pct_fp"], 0)]
        rows.append(row)
    head = ["Variant"] + [f"{CAM[c]}: {h}" for c in cams for h in ("clean pixels flagged", "clean frames with a false hand", "hand pixels found at 1 % false positives")]
    out["ablation"] = table(head, rows)

    # Thresholds.
    rows = []
    for cam, r in cams.items():
        for key in ("LOW", "HIGH"):
            t = r["chosen_thresholds"][key]
            rows.append([CAM[cam], f"{key} = {t['threshold']}", p(t["fpr"]), p(t["recall"])])
    out["thresholds"] = table(["Camera", "Threshold (grey levels)", "Clean pixels above it", "Hand pixels above it"], rows)
    rows = []
    for cam, r in cams.items():
        for s in r["sweep"]:
            rows.append([CAM[cam], f"{s['low']:.1f} / {s['high']:.1f}" + (" (chosen)" if s["scale"] == 1.0 else ""),
                         p(s["clean_mask_fp"]), p(s["false_alarm_frames"], 0), p(s["recall"], 0), p(s["hand_found"], 0)])
    out["sweep"] = table(["Camera", "LOW / HIGH", "Clean pixels flagged", "Clean frames with a false hand", "Hand pixels found", "Hand found"], rows)

    # Per class and failures.
    rows = []
    for c in results["classes"]:
        for cam, r in cams.items():
            v = r["per_class"][c]
            rows.append([c, CAM[cam], p(v["clean_mask_fp"]), p(v["false_alarm_frames"], 0), p(v["shadow_recall"], 0), p(v["hand_recall"], 0),
                         n(v["tip_median_px"], 0, " px")])
    out["per_class"] = table(["Content", "Camera", "Clean pixels flagged", "Clean frames with a false hand", "Shadow pixels found", "Lit-hand pixels found", "Median tip error"], rows)
    rows = []
    for name in cams["0"]["per_picture"]:
        cells = [name, cams["0"]["per_picture"][name]["class"]]
        for cam, r in cams.items():
            v = r["per_picture"][name]
            cells += [p(v["clean_mask_fp"]), p(v["hand_found"], 0), n(v["tip_median_px"], 0, " px")]
        rows.append(cells)
    rows.sort(key=lambda row: -max(float(row[2].rstrip(" %").replace("–", "0")), float(row[5].rstrip(" %").replace("–", "0"))))
    out["per_picture"] = table(["Picture", "Class"] + [f"{CAM[c]}: {h}" for c in cams for h in ("clean pixels flagged", "hand found", "median tip error")], rows)

    # Fingertip.
    rows = [[CAM[cam], r["fingertip"]["frames"], p(r["fingertip"]["found_rate"], 0), n(r["fingertip"]["median_px"]), n(r["fingertip"]["median_pct_width"], 2, " %"),
             n(r["fingertip"]["p90_px"], 0), p(r["fingertip"]["within_20px"], 0)] for cam, r in cams.items()]
    out["fingertip"] = table(["Camera", "Frames with a hand", "Hand found", "Median error (px)", "Median (% of width)", "90th percentile (px)", "Found tips within 20 px"], rows)

    # Calibration.
    rows = [[CAM[cam], f"{c['markers']} / {c['markers_total']}", n(c["rms_px"], 2), n(c["median_px"], 2), n(c["max_px"], 1),
             ", ".join(f"{v:.2f}" for v in c["repeat_rms_px"]), n(c["other_session_rms_px"], 2)] for cam, c in results["calibration"].items()]
    out["calibration"] = table(["Camera", "Markers found", "RMS error (px)", "Median corner error (px)", "Worst corner (px)",
                                "RMS over 3 photos (px)", "Same H on the other session's photo (px)"], rows)

    # MediaPipe.
    m = results.get("mediapipe")
    if m:
        keys = [("clean_full", "clean frame, whole image"), ("hand_full", "synthetic hand, whole image"),
                ("hand_engine_crop", "synthetic hand, engine's crop"), ("hand_true_crop", "synthetic hand, crop at the true tip")]
        out["mediapipe"] = table(["Input"] + [f"{CAM[c]}: fired" for c in m], [[label] + [f"{m[c][k]['fired']} / {m[c][k]['frames']}" for c in m] for k, label in keys])
        if all("ms_full_frame" in m[c] for c in m):
            out["mediapipe"] += "\n\nTime per call on this laptop (median): " + "; ".join(
                f"{CAM[c]}: whole frame {m[c]['ms_full_frame']:.0f} ms, crop {m[c]['ms_crop']:.0f} ms" for c in m) + "."
    else:
        out["mediapipe"] = "Not run (use `python -m eval.experiments` without `--no-mediapipe`)."

    # Rig reports.
    rows = []
    for cam, report in rig["live"].items():
        for r in report["pictures"]:
            rows.append([report["label"], r["picture"], p(r["false_alarm_frames"], 0)] +
                        [f"{p(r[k]['found'], 0)}, {n(r[k]['median_error_px'], 0, ' px')}" for k in ("shadow", "hand")])
    out["live"] = table(["Camera", "Picture", "Clean: frames with a false hand", "Shadow: frames with a pointer, median error", "Lit hand: same"], rows) if rows else "No live report yet."
    apps = list(dict.fromkeys(a for r in rig["idle"].values() for a in r))
    out["idle"] = table(["App"] + [f"{CAM.get(c, c)}: false-hand frames" for c in rig["idle"]],
                        [[a] + [f"{r[a]['false_alarm_frames']} / {r[a]['frames']}" if a in r else "–" for r in rig["idle"].values()] for a in apps]) if apps else "No idle report yet."
    if k:
        out["keystone"] = table(["", "Edge tilt", "Aspect ratio (target 1.78)", "Markers found"],
                                [[w, f"{k[key]['tilt_degrees']:.2f}°", f"{k[key]['aspect']:.3f}", k[key]["markers"]] for key, w in (("plain", "Before"), ("corrected", "After"))]) \
            + f"\n\nPointer error inside the corrected picture (synthetic shadow): median {n(k['pointer_error_px']['median'])} px over {k['pointer_error_px']['frames']} frames."
    else:
        out["keystone"] = "No keystone report yet."
    rows = [[r["label"], n(r.get("camera_delay_ms"), 0, " ms"), n(r["ms_per_frame"], 0, " ms"), n(cams[c]["ms_per_frame_residual"], 0, " ms") if c in cams else "–"]
            for c, r in rig["live"].items()]
    out["latency"] = table(["Camera", "Camera + projector delay (calibration)", "Engine step, live (median)", "Residual only, offline (median)"], rows) if rows else "No live report yet."

    # Real hands.
    if real:
        out["real_hands"] = table(["Taps", "Sessions", "Median error", "Mean error", "90th percentile", "Median time per target"],
                                  [[real["taps"], real["sessions"], f"{n(real['median_error_px'])} px ({n(real['median_error_pct_width'], 2)} % of width)",
                                    f"{n(real['mean_error_px'])} px", f"{n(real['p90_error_px'])} px", f"{n(real['median_time_s'], 2)} s"]])
    else:
        out["real_hands"] = "**Not yet measured.** The Accuracy app writes every tap to `~/.visiontouch/log.jsonl`; run `python -m eval.fill_report` after a session and this table fills in."
    out["generated"] = f"_Numbers generated {results['generated']} from `runs/figures/results.json` and the rig reports by `eval/fill_report.py`._"
    return out


def fill(path, values):
    text = path.read_text()
    names = re.findall(r"<!-- BEGIN (\w+) -->", text)
    unknown = [name for name in names if name not in values]
    if unknown:
        raise SystemExit(f"{path}: unknown blocks {unknown}")
    for name in names:
        text = re.sub(rf"(<!-- BEGIN {name} -->\n).*?(<!-- END {name} -->)", lambda m: m.group(1) + values[name] + "\n" + m.group(2), text, flags=re.S)
    path.write_text(text)
    return names


def missing_figures(path):
    """Linked images that do not exist, relative to the document."""
    links = re.findall(r"!\[[^\]]*\]\(([^)\s]+)\)", path.read_text())
    return [link for link in links if not link.startswith("http") and not (path.parent / link).exists()]


def main():
    results = json.loads(ex.RESULTS.read_text())
    values = blocks(results, ex.rig_reports(), ex.real_hands())
    missing = []
    for path in DOCUMENTS:
        if path.exists():
            print(f"{path}: filled {fill(path, values)}")
            missing += [f"{path}: {link}" for link in missing_figures(path)]
    if missing:
        print("missing figures:\n  " + "\n  ".join(missing))
        sys.exit(1)


if __name__ == "__main__":
    main()
