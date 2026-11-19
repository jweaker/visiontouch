"""Start VisionTouch or verify its packaged resources headlessly."""
import argparse
import os
import sys
import webbrowser


def check(output):
    from socket import socket
    from threading import Thread
    from urllib.request import ProxyHandler, build_opener

    try:
        os.environ["MPLBACKEND"] = "Agg"
        import av
        import cv2
        import mediapipe as mp
        import numpy as np

        from visiontouch.hands import Landmarker
        from visiontouch.server import Server, WEB_DIR

        print(f"Python {sys.version.split()[0]}", file=output)
        print(f"OpenCV {cv2.__version__}", file=output)
        print(f"NumPy {np.__version__}", file=output)
        print(f"MediaPipe {mp.__version__}", file=output)

        index = (WEB_DIR / "index.html").read_bytes()
        if b'src="/assets/' not in index:
            raise RuntimeError("stage index.html has no built JavaScript asset")

        with socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        server = Server(port)
        start = Thread(target=server.start, daemon=True)
        start.start()
        start.join(timeout=5)
        if start.is_alive():
            raise RuntimeError(f"local stage server failed to start on port {port}")
        with build_opener(ProxyHandler({})).open(f"http://127.0.0.1:{port}/", timeout=5) as response:
            if response.headers.get_content_type() != "text/html" or response.read() != index:
                raise RuntimeError("local server did not serve the built stage HTML")
        print("Stage HTML OK", file=output)

        blank = np.zeros((64, 64, 3), np.uint8)
        if Landmarker().detect(blank, (32, 32), 32) is not None:
            raise RuntimeError("hand landmark model detected a hand in a blank image")
        print("Hand landmark model OK", file=output)
        av.CodecContext.create("h264", "r")
        print("PyAV H.264 decoder OK", file=output)
    except Exception as exc:
        print(f"VisionTouch self-check failed: {exc}", file=output)
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(prog="visiontouch", description="Turn a projector and a camera into a touch surface.")
    parser.add_argument("--camera", default="0", help='camera index, "android" for a phone over USB, or a video URL/file')
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--windowed", action="store_true", help="do not go fullscreen")
    parser.add_argument("--browser", action="store_true", help="open the stage in the default browser instead of the built-in window")
    parser.add_argument("--no-landmarks", action="store_true", help="classical detection only (no MediaPipe)")
    parser.add_argument("--record", metavar="FOLDER", help="save camera frames and screen pictures for offline replay (python -m eval.replay)")
    parser.add_argument("--check", action="store_true", help="verify the stage and hand model without a window or camera")
    parser.add_argument("--check-log", metavar="FILE", help="write self-check output to a file")
    args = parser.parse_args()

    if args.check:
        if args.check_log:
            with open(args.check_log, "w", encoding="utf-8") as output:
                return check(output)
        if sys.platform == "win32" and sys.stdout is None:
            from ctypes import windll

            windll.kernel32.AttachConsole(-1)
            try:
                console = open("CONOUT$", "w", encoding="utf-8")
            except OSError:
                return check(sys.stderr)
            with console as output:
                return check(output)
        return check(sys.stdout)

    from visiontouch.engine import Engine

    def run_engine(server):
        engine = Engine(server, args.camera, landmarks=not args.no_landmarks)
        if args.record:
            engine.record(args.record)
        engine.run()

    frozen_linux = sys.platform.startswith("linux") and getattr(sys, "frozen", False)
    if args.browser or frozen_linux:
        from visiontouch.server import Server

        server = Server(args.port)
        server.start()
        url = f"http://127.0.0.1:{args.port}/"
        if frozen_linux:
            from subprocess import Popen

            # The system browser must load its own libraries.
            env = os.environ.copy()
            env.pop("LD_LIBRARY_PATH", None)
            if "LD_LIBRARY_PATH_ORIG" in env:
                env["LD_LIBRARY_PATH"] = env["LD_LIBRARY_PATH_ORIG"]
            Popen(["xdg-open", url], env=env)
        else:
            webbrowser.open(url)
        run_engine(server)
    else:
        if sys.platform == "win32":
            os.environ["PYWEBVIEW_GUI"] = "edgechromium"
            if sys.stdout is None:
                sys.stdout = sys.stderr = open(os.devnull, "w", encoding="utf-8")
        from visiontouch.app import run

        run(run_engine, args.port, fullscreen=not args.windowed)


if __name__ == "__main__":
    raise SystemExit(main())
