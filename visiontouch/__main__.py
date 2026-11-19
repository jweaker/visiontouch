"""Start VisionTouch:  python -m visiontouch [--camera 0] [--windowed] [--browser]"""
import argparse
import time
import webbrowser

from .engine import Engine
from .server import Server

parser = argparse.ArgumentParser(prog="visiontouch", description="Turn a projector and a camera into a touch surface.")
parser.add_argument("--camera", default="0", help='camera index, "android" for a phone over USB, or a video URL/file')
parser.add_argument("--port", type=int, default=8765)
parser.add_argument("--windowed", action="store_true", help="do not go fullscreen")
parser.add_argument("--browser", action="store_true", help="open the stage in the default browser instead of the built-in window")
parser.add_argument("--no-landmarks", action="store_true", help="classical detection only (no MediaPipe)")
args = parser.parse_args()


def main(server):
    Engine(server, args.camera, landmarks=not args.no_landmarks).run()


if args.browser:
    server = Server(args.port)
    server.start()
    webbrowser.open(f"http://127.0.0.1:{args.port}/")
    main(server)
else:
    from .app import run

    run(main, args.port, fullscreen=not args.windowed)
