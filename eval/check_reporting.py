"""Self-check for the reporting helpers: python -m eval.check_reporting"""
import json
import tempfile
from pathlib import Path

from eval.experiments import real_hands, report_label
from eval.fill_report import fill, missing_figures

with tempfile.TemporaryDirectory() as folder:
    folder = Path(folder)
    # The accuracy log: only engine taps ("touch") count; mouse taps and junk lines are ignored.
    log = folder / "log.jsonl"
    assert real_hands(log) is None
    tap = lambda error, kind: json.dumps({"t": "log", "name": "accuracy", "data": {
        "session": "s", "input": kind, "w": 1920, "error_px": error, "error_pct_width": 100 * error / 1920, "time_ms": 900}})
    log.write_text("\n".join([tap(10, "touch"), tap(30, "touch"), tap(500, "mouse"), "not json", tap(20, "touch")]))
    r = real_hands(log)
    assert r["taps"] == 3 and r["median_error_px"] == 20 and r["median_time_s"] == 0.9, r
    log.write_text(tap(5, "mouse"))
    assert real_hands(log) is None

    # Blocks are replaced, text around them kept; unknown blocks and missing figures are reported.
    doc = folder / "doc.md"
    doc.write_text("intro\n<!-- BEGIN a -->\nold\n<!-- END a -->\nmiddle ![f](missing.png) <!-- ![x](ignored.png) -->\n")
    assert fill(doc, {"a": "new"}) == ["a"]
    assert doc.read_text() == "intro\n<!-- BEGIN a -->\nnew\n<!-- END a -->\nmiddle ![f](missing.png) <!-- ![x](ignored.png) -->\n"
    assert missing_figures(doc) == ["missing.png"]
    try:
        fill(doc, {})
        raise AssertionError("unknown block accepted")
    except SystemExit:
        pass

assert report_label("0") == "Webcam" and report_label("android") == "Phone"
assert report_label("0_washed") == "Webcam, washed-out picture" and report_label("3") == "Camera 3"
print("ok")
