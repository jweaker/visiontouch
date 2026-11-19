"""False-alarm test with the real stage and nobody in the room.

    python -m eval.idle_test [camera]

Opens every app in turn and counts frames in which the engine reports a hand.
There is no hand, so every report is a false alarm.
"""
import json
import sys
import time
from pathlib import Path

from visiontouch.app import run
from visiontouch.engine import Engine

CAMERA = sys.argv[1] if len(sys.argv) > 1 else "0"
APPS = ["", "board", "balloons", "catch", "slides", "quiz", "memory", "accuracy", "pipeline", "settings"]
OUT = Path("runs/idle")


def main(server):
    assert server.wait_for_stage(), "stage window did not connect"
    server.viewers = 1  # keep debug images coming: this test saves them
    OUT.mkdir(parents=True, exist_ok=True)
    engine = Engine(server, CAMERA)
    if "--calibrate" in sys.argv or engine.predictor is None:
        assert engine.calibrate(), engine.message
    print(engine.message or "using saved calibration", flush=True)
    report = {}
    for app in APPS:
        server.view.evaluate_js(f"location.hash = '#{app}'")
        time.sleep(2.0)
        frames, alarms, end = 0, 0, time.monotonic() + 4
        while time.monotonic() < end:
            pointers = engine.step()
            if pointers is not None:
                frames, alarms = frames + 1, alarms + bool(pointers)
        report[app or "launcher"] = {"frames": frames, "false_alarm_frames": alarms}
        print(f"{app or 'launcher':<10} {frames:4d} frames, {alarms:3d} with a false hand", flush=True)
        for stage in ("overlay", "residual"):
            (OUT / f"{app or 'launcher'}_{stage}.jpg").write_bytes(server._debug[stage])
    (OUT / f"report_{CAMERA.split(':')[0]}.json").write_text(json.dumps(report, indent=1))
    engine.camera.close()


if __name__ == "__main__":
    run(main)
