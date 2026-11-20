"""Builds the final presentation, docs/slides/VisionTouch.pptx, from the figures
and numbers the evaluation produced.

    uv run python -m eval.experiments && uv run python -m eval.figures   # first
    uv run python docs/slides/build.py

Every number on a slide is read from runs/figures/results.json or the rig
reports, never typed in. Each slide has speaker notes so any member can present.
PDF: if LibreOffice is installed, `soffice --headless --convert-to pdf
docs/slides/VisionTouch.pptx --outdir docs/slides`; otherwise open the file in
PowerPoint or Keynote and export as PDF.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pptx import Presentation  # noqa: E402
from pptx.dml.color import RGBColor  # noqa: E402
from pptx.util import Inches, Pt  # noqa: E402

from eval import experiments as ex  # noqa: E402

FIGURES = ROOT / "runs" / "figures"
OUT = Path(__file__).parent / "VisionTouch.pptx"
INK, MUTED, ACCENT, PAPER = RGBColor(0x0B, 0x0B, 0x0B), RGBColor(0x52, 0x51, 0x4E), RGBColor(0x2A, 0x78, 0xD6), RGBColor(0xFF, 0xFF, 0xFF)
W, H = Inches(13.333), Inches(7.5)
TEAM = ["[Member 1]", "[Member 2]", "[Member 3]", "[Member 4]", "[Member 5]"]


def text(slide, x, y, w, h, lines, size=24, colour=INK, bold=False):
    """A text box; `lines` is a string or a list of paragraphs."""
    box = slide.shapes.add_textbox(x, y, w, h)
    frame = box.text_frame
    frame.word_wrap = True
    for i, line in enumerate([lines] if isinstance(lines, str) else lines):
        para = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        para.text = line
        para.space_after = Pt(size * 0.5)
        for run in para.runs:
            run.font.size, run.font.color.rgb, run.font.bold, run.font.name = Pt(size), colour, bold, "Calibri"
    return box


def slide(deck, title, notes, kicker=None):
    s = deck.slides.add_slide(deck.slide_layouts[6])  # blank
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = PAPER
    if kicker:
        text(s, Inches(0.6), Inches(0.25), Inches(12), Inches(0.5), kicker, 16, ACCENT, True)
    text(s, Inches(0.6), Inches(0.55), Inches(12.2), Inches(1.0), title, 36, INK, True)
    s.notes_slide.notes_text_frame.text = notes
    return s


def picture(s, name, x=Inches(0.6), y=Inches(1.55), w=None, h=Inches(5.7)):
    path = FIGURES / f"{name}.png"
    if not path.exists():
        text(s, x, y, Inches(8), Inches(1), f"[figure {name}.png missing: run eval/figures.py]", 20, MUTED)
        return
    pic = s.shapes.add_picture(str(path), x, y, height=h) if w is None else s.shapes.add_picture(str(path), x, y, width=w)
    if pic.left + pic.width > W:  # keep inside the slide
        scale = (W - x - Inches(0.3)) / pic.width
        pic.width, pic.height = int(pic.width * scale), int(pic.height * scale)
    return pic


def pct(v, digits=0):
    return "–" if v is None else f"{100 * v:.{digits}f} %"


def build():
    r = json.loads(ex.RESULTS.read_text())
    rig, real = ex.rig_reports(), ex.real_hands()
    cams = r["cameras"]
    first, full = r["variants"][0], r["variants"][-1]
    deck = Presentation()
    deck.slide_width, deck.slide_height = W, H

    # 1. Title
    s = slide(deck, "VisionTouch: a smart projector board from one camera",
              "Introduce the team and the one-sentence idea: any projector plus any camera becomes a touch board, using only image processing. "
              "Say this is the Digital Image Processing course project and that we will follow the course phases: problem, data, method, results.")
    text(s, Inches(0.6), Inches(2.0), Inches(12), Inches(1), "Point, hold or pinch to click, palm to erase, swipe for slides. No special hardware.", 26, MUTED)
    text(s, Inches(0.6), Inches(4.6), Inches(12), Inches(2), ["Digital Image Processing, course project", "Team: " + ", ".join(TEAM)], 22, INK)

    # 2. Problem and idea
    s = slide(deck, "Problem: touch boards need special hardware", kicker="Phase 1 · Problem",
              notes="Interactive whiteboards need a touch panel, an infrared curtain or a special pen. Many classrooms already have a projector and every laptop has a camera. "
                    "The difficulty: the camera does not see a quiet background but the projected picture, which changes all the time, and the hand is lit by that picture. "
                    "Our idea: the computer knows what it projects, so it can predict what the camera should see. Whatever differs is a hand or its shadow.")
    text(s, Inches(0.6), Inches(1.8), Inches(6), Inches(5), [
        "Classrooms already have a projector and a laptop camera.",
        "But the camera sees a moving picture, not a quiet background.",
        "Idea: predict what the camera should see, then subtract.",
        "g(x, y) = camera(x, y) − predicted(x, y)"], 26)
    picture(s, "pipeline_good", x=Inches(6.8), y=Inches(1.8), w=Inches(6.2))

    # 3. Related work
    s = slide(deck, "Related work", kicker="Phase 1 · Literature",
              notes="Predicted-image subtraction is the published method for projector-camera systems (Nayar, Fujii, Jaynes, Castañeda-Garay). "
                    "None of them handles a camera that changes its exposure by itself, which webcams and phones do: we added that. "
                    "PlayAnywhere uses infrared to detect touch from the shadow; we only have visible light. "
                    "MediaPipe Hands is a learned landmark model. Open-source projects run a hand model on the raw frame and report about 100 ms delay. "
                    "All references are numbered in docs/related-work.md.")
    text(s, Inches(0.6), Inches(1.8), Inches(12), Inches(5), [
        "Predicted-image subtraction for projector-camera systems [1–4]: fixed camera exposure assumed.",
        "Plain subtraction finds hand and shadow together: high recall, low precision [6].",
        "Touch from the finger's shadow, with an infrared camera: PlayAnywhere [13].",
        "MediaPipe Hands: 21 landmarks from a neural network [32]; not tested in unusual light [33].",
        "Open-source projector touch projects: hand model on the raw frame, about 100 ms delay [45].",
        "New in our work: per-frame exposure adaptation and per-row banding correction."], 22)

    # 4. Data
    c0 = cams["0"]["frames"]
    s = slide(deck, "Data: our own recordings on a real projector", kicker="Phase 2 · Data",
              notes=f"We recorded every test picture with both cameras at once: the MacBook webcam near the projector, and an Android phone 1.2 m to the side. "
                    f"23 pictures: plain colours, slides, text, a drawing, a game, six photos and a desktop. Each one clean, with a synthetic black shadow, and with a synthetic skin-tinted hand, "
                    f"three frames each: {c0['clean']} clean and {c0['with_hand']} hand frames per camera. The hand is painted into the projected picture, so we know the exact mask and fingertip. "
                    "Be clear: these are not real hands. They test the camera, projector and pipeline, not skin or 3-D shadows.")
    picture(s, "dataset", x=Inches(0.6), y=Inches(1.5), h=Inches(5.8))

    # 5. Pipeline
    s = slide(deck, "The pipeline, and which lecture each step uses", kicker="Phase 2 · Design",
              notes="Walk through the steps left to right, one sentence each. Calibration happens on first start and again by itself if the camera or projector is knocked; everything else runs every frame. "
                    "The delay between screen and camera is only known roughly, so the engine compares with every screenshot shown within 0.15 s of the expected moment. "
                    "Lecture links: colour images and resolution (capture), point processing and intensity transformations (colour map, exposure), image subtraction (residual), "
                    "spatial filtering (local min and max), thresholding and binary images (mask), power-law gamma and smoothing (keystone). "
                    "Beyond the lectures: homography, polynomial regression, Kalman filter, MediaPipe.")
    steps = [("Calibrate", "markers → homography\ncolour tiles → colour map", "beyond: homography,\nregression"),
             ("Predict", "warp screenshot,\nexposure, banding", "point processing,\nintensity transforms"),
             ("Subtract", "residual against local\nmin..max of nearby\nscreenshots", "image subtraction,\nspatial filtering"),
             ("Mask", "hysteresis threshold,\nopening, closing,\ngroup nearby pieces", "thresholding,\nbinary images"),
             ("Fingertip", "farthest solid point\nfrom where the arm\nenters", "binary image\ngeometry"),
             ("Pose + track", "MediaPipe on a crop,\nKalman filter", "beyond: CNN,\nKalman")]
    for i, (name, what, lecture) in enumerate(steps):
        x = Inches(0.5 + i * 2.1)
        box = s.shapes.add_shape(1, x, Inches(2.0), Inches(1.95), Inches(1.0))
        box.fill.solid()
        box.fill.fore_color.rgb = ACCENT
        box.line.fill.background()
        box.text_frame.text = name
        for run in box.text_frame.paragraphs[0].runs:
            run.font.size, run.font.bold, run.font.color.rgb = Pt(22), True, PAPER
        text(s, x, Inches(3.2), Inches(1.95), Inches(1.6), what.split("\n"), 17, INK)
        text(s, x, Inches(4.9), Inches(1.95), Inches(1.6), lecture.split("\n"), 17, MUTED)
    text(s, Inches(0.5), Inches(6.5), Inches(12), Inches(0.6), "Grey: the matching lecture topic.", 16, MUTED)

    # 6. Intermediate outputs
    s = slide(deck, "Intermediate outputs: from camera frame to fingertip", kicker="Phase 3 · Implementation",
              notes="Six panels: the camera frame cropped to the picture; the screenshot warped into the camera's view; the predicted image (note the rainbow bands it reproduces); "
                    "the residual, bright where the camera disagrees; the mask after thresholding and morphology; and the fingertip, white circle true, red cross found. "
                    "Point out the black gaps along text lines in the residual: black text stays black under a hand.")
    picture(s, "pipeline_good", x=Inches(0.9), y=Inches(1.5), h=Inches(5.9))

    # 7. Banding
    s = slide(deck, "Rainbow banding, and how we remove it", kicker="Phase 3 · Implementation",
              notes="The projector shows red, green and blue one after another. The camera reads its rows one after another, so each row catches a different mix: moving rainbow bands. "
                    "For every row we solve for three numbers, the strength of red, green and blue, by least squares, and correct the prediction. "
                    "The plot on the right shows the mean residual per row before and after.")
    picture(s, "banding", x=Inches(0.9), y=Inches(1.5), h=Inches(5.9))

    # 8. Ablation
    a = {cam: cams[cam]["ablation"] for cam in cams}
    s = slide(deck, "Alternative methods: every step earns its place", kicker="Phase 4 · Evaluation",
              notes="We switched on one step at a time and scored all pictures. Left: clean pixels wrongly flagged with the real thresholds. "
                    f"Plain subtraction with one brightness fit flags {pct(a['0'][first]['clean_mask_fp'])} (webcam); the full method {pct(a['0'][full]['clean_mask_fp'], 1)}. "
                    "The colour map alone does not help, because the camera's exposure changed since calibration; it pays off with exposure adaptation. "
                    "Right: a threshold-free comparison, hand pixels found when only 1 % of clean pixels may be flagged.")
    picture(s, "ablation", x=Inches(0.9), y=Inches(1.5), h=Inches(5.9))

    # 9. Thresholds
    t = cams["0"]["chosen_thresholds"]
    s = slide(deck, "Parameter test: the detection thresholds", kicker="Phase 4 · Evaluation",
              notes="ROC curves: every point is one threshold; up and left is better. The circle and square are our chosen LOW and HIGH. "
                    f"At LOW = {t['LOW']['threshold']} the webcam flags {pct(t['LOW']['fpr'], 1)} of clean pixels and finds {pct(t['LOW']['recall'])} of hand pixels, before morphology. "
                    "Hysteresis uses HIGH to decide a blob is real and LOW to find its full size. The sweep in the report shows somewhat higher thresholds would do slightly better on this dataset.")
    picture(s, "roc", x=Inches(0.9), y=Inches(1.5), h=Inches(5.9))

    # 10. Per class
    s = slide(deck, "Results by kind of content", kicker="Phase 4 · Evaluation",
              notes="Plain colours, drawings and games, and light slides work well. Photos and the desktop screenshot are the hard class: "
                    f"false hands in {pct(cams['0']['per_class']['photos and desktop']['false_alarm_frames'])} of clean webcam frames. "
                    "These offline numbers are single frames, before the tracker's three-frame confirmation, and on the data we developed on.")
    picture(s, "per_class", x=Inches(0.9), y=Inches(1.5), h=Inches(5.9))

    # 11. Failure case
    s = slide(deck, "Failure case: a detailed photo", kicker="Phase 4 · Failure cases",
              notes="On a photo with leaves and fine detail, the residual is high everywhere, not just on the hand. False blobs join the hand and the fingertip lands far away. "
                    "Other failures: on black there is no light to block, so a shadow is invisible; dense text breaks the hand's blob into pieces. "
                    "The same physics shapes our apps: a hand is invisible over anything dark, so the cursor ring is bright, the Board draws in blue, and game sprites are outlined in a darker shade of their own colour.")
    picture(s, "pipeline_failure", x=Inches(0.9), y=Inches(1.5), h=Inches(5.9))

    # 12. Live rig and speed
    live = rig["live"]
    delays = ", ".join(f"{v['label']} {v['camera_delay_ms']} ms" for v in live.values() if v.get("camera_delay_ms"))
    steps_ms = ", ".join(f"{v['label']} {v['ms_per_frame']:.0f} ms" for v in live.values())
    alarms = max((r_["false_alarm_frames"] for v in live.values() for r_ in v["pictures"]), default=None)
    idle = [(n_ / max(c_["frames"], 1), app, cam) for cam, report in rig["idle"].items() for app, c_ in report.items() for n_ in [c_["false_alarm_frames"]]]
    worst_idle = max(idle, default=None)
    s = slide(deck, "Live on the real rig", kicker="Phase 4 · Evaluation",
              notes="The engine calibrated itself, then the test projected synthetic hands at random places while the engine was told the screen was clean. "
                    "Left: share of frames with a pointer; right: median pointer error. Dense text is the clear failure. "
                    f"Clean pictures with nobody in front: at most {pct(alarms)} of frames had a false pointer. "
                    + (f"Idle test over all apps: worst was {worst_idle[1]} with the {ex.report_label(worst_idle[2]).lower()} camera, {pct(worst_idle[0])} of frames. " if worst_idle else "")
                    + f"Camera plus projector delay measured at calibration: {delays}. Engine time per frame: {steps_ms}.")
    picture(s, "live", x=Inches(0.9), y=Inches(1.5), h=Inches(5.9))

    # 13. Keystone
    k = rig["keystone"].get("0")
    s = slide(deck, "Automatic keystone correction", kicker="Phase 3 · Implementation",
              notes=("We find the projection screen's frame with a gamma lift (power-law transformation), smoothing and a brightness-change test, fit four lines, "
                     "and draw the picture pre-distorted inside the largest upright 16:9 rectangle. "
                     + (f"Measured: edge tilt {k['plain']['tilt_degrees']:.1f} degrees before, {k['corrected']['tilt_degrees']:.2f} after; "
                        f"aspect {k['plain']['aspect']:.2f} before, {k['corrected']['aspect']:.2f} after (target 1.78)." if k else "No keystone report yet.")))
    picture(s, "keystone", x=Inches(0.6), y=Inches(1.8), w=Inches(12.1))

    # 14. Limits and next steps
    m = r.get("mediapipe", {})
    fired = sum(m[c]["hand_full"]["fired"] for c in m) if m else None
    frames = sum(m[c]["hand_full"]["frames"] for c in m) if m else None
    s = slide(deck, "Honest limits, and what comes next", kicker="Conclusion",
              notes="Say this plainly. Every hand so far is synthetic. We have not measured real skin, real 3-D shadows, pinch on a real hand, or a body blocking the camera. "
                    "The Windows and Linux builds have not been run on real hardware; only CI's headless self-check has passed. "
                    f"MediaPipe fired on {fired} of {frames} synthetic-hand frames on the whole image, which says nothing about real hands. "
                    "Real-hand accuracy: " + (f"median {real['median_error_px']:.0f} px over {real['taps']} taps." if real else "not yet measured; the Accuracy app logs every tap and the report fills in automatically.")
                    + " Next: real-hand test, touch from the shadow, separating hand from shadow by colour, and lower delay.")
    text(s, Inches(0.6), Inches(1.8), Inches(6.2), Inches(5.4), [
        "All test hands so far are synthetic.",
        "Not yet measured: real skin, 3-D shadows, pinch, body blocking the camera.",
        "Real-hand accuracy: " + (f"median {real['median_error_px']:.0f} px" if real else "not yet measured."),
        "Photos, black areas and dense text fail.",
        "No depth: a click is a pause or a pinch.",
        "Windows and Linux builds: headless self-check only."], 22)
    text(s, Inches(7.0), Inches(1.8), Inches(5.8), Inches(5.4), [
        "Next steps",
        "Real-hand test with the Accuracy app",
        "Touch versus hover from the finger's shadow",
        "Hand versus shadow by colour",
        "Re-tune thresholds on real hands",
        "Lower delay: lock exposure, faster camera"], 22, ACCENT)

    deck.save(OUT)
    print(f"wrote {OUT} ({len(deck.slides)} slides)")


if __name__ == "__main__":
    build()
