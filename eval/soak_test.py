"""Leaves the real app running through every screen with nobody in the room.

    python -m eval.soak_test [camera] [seconds per screen]

Nothing should happen: no hands, no recalibration. Reports what did.
"""
import json
import sys
import threading
import time
from pathlib import Path

from visiontouch.app import run
from visiontouch.engine import Engine

CAMERA = sys.argv[1] if len(sys.argv) > 1 else "0"
SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 8
APPS = ["", "board", "balloons", "catch", "slides", "quiz", "memory", "accuracy", "pipeline", "settings"]


def main(server):
    assert server.wait_for_stage(), "stage window did not connect"
    engine = Engine(server, CAMERA)
    assert engine.predictor is not None, "calibrate first (run the app once)"
    hands, messages = {}, []
    send = server.send

    def spy(message):  # count frames in which the engine reported a hand
        if message.get("t") == "pointers" and message["p"]:
            hands[current] = hands.get(current, 0) + 1
        send(message)

    server.send = spy
    threading.Thread(target=engine.run, daemon=True).start()
    for current in APPS:
        current = current or "launcher"
        server.view.evaluate_js(f"location.hash = '#{'' if current == 'launcher' else current}'")
        end = time.monotonic() + SECONDS
        while time.monotonic() < end:
            if engine.message and (not messages or messages[-1][1] != engine.message):
                messages.append((current, engine.message))
            time.sleep(0.1)
        print(f"{current:<10} frames with a false hand: {hands.get(current, 0)}, fps {engine.fps:.0f}", flush=True)
    report = {"camera": CAMERA, "seconds_per_screen": SECONDS, "false_hand_frames": hands, "messages": messages}
    Path("runs/idle").mkdir(parents=True, exist_ok=True)
    Path(f"runs/idle/soak_{CAMERA.split(':')[0]}.json").write_text(json.dumps(report, indent=1))
    print("engine messages:", messages or "none", flush=True)


if __name__ == "__main__":
    run(main)
