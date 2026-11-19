"""Camera sources. A reader thread keeps only the newest frame, so the engine
never processes stale images.

Source strings:
  "0", "1", ...        a camera the OS knows (webcam, Continuity Camera, virtual cam)
  "android[:serial]"   the back camera of an Android 12+ phone over USB (needs scrcpy + adb)
  anything else        a URL or video file path that OpenCV can open
"""
import os
import random
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import cv2

PHONE_JAR = "/data/local/tmp/visiontouch-scrcpy-server.jar"


class PhoneStream:
    """Back camera of an Android phone over USB. Runs the scrcpy server on the
    phone in camera mode and decodes its raw H.264 stream. Only the camera is
    opened: the phone's screen and input are left alone."""

    def __init__(self, serial, size):
        import av  # imported here so the other sources work without it

        scrcpy, adb = shutil.which("scrcpy"), shutil.which("adb")
        if not scrcpy or not adb:
            raise RuntimeError("the android camera needs scrcpy and adb installed")
        exe = Path(scrcpy).resolve()
        jar = os.environ.get("SCRCPY_SERVER_PATH")
        candidates = [jar] if jar else [exe.parent.parent / "share/scrcpy/scrcpy-server", exe.parent / "scrcpy-server"]
        jar = next((str(p) for p in candidates if Path(p).exists()), None)
        if not jar:
            raise RuntimeError("scrcpy-server not found; set SCRCPY_SERVER_PATH")
        version = subprocess.run([scrcpy, "--version"], capture_output=True, text=True).stdout.split()[1]
        adb = [adb, "-s", serial] if serial else [adb]
        scid, port = f"{random.getrandbits(31):08x}", random.randint(27200, 27999)
        subprocess.run([*adb, "push", jar, PHONE_JAR], check=True, capture_output=True)
        subprocess.run([*adb, "forward", f"tcp:{port}", f"localabstract:scrcpy_{scid}"], check=True, capture_output=True)
        self._unforward = [*adb, "forward", "--remove", f"tcp:{port}"]
        self._proc = subprocess.Popen(
            [*adb, "shell", f"CLASSPATH={PHONE_JAR}", "app_process", "/", "com.genymobile.scrcpy.Server", version,
             f"scid={scid}", "tunnel_forward=true", "audio=false", "control=false", "cleanup=false",
             "raw_stream=true", "video_source=camera", "camera_facing=back",
             f"camera_size={size[0]}x{size[1]}", "camera_fps=30", "video_bit_rate=16000000"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self._codec = av.CodecContext.create("h264", "r")
        self._sock, self._data = None, b""
        end = time.monotonic() + 8
        while time.monotonic() < end and not self._data:  # adb accepts before the server is ready
            try:
                sock = socket.create_connection(("127.0.0.1", port), timeout=1)
                self._data = sock.recv(65536)
                if self._data:
                    self._sock = sock
                else:
                    sock.close()
                    time.sleep(0.1)
            except OSError:
                time.sleep(0.1)

    def isOpened(self):
        return self._sock is not None

    def read(self):
        while self._data:
            packets = self._codec.parse(self._data)
            self._data = self._sock.recv(65536)
            frames = [f for p in packets for f in self._codec.decode(p)]
            if frames:
                return True, frames[-1].to_ndarray(format="bgr24")
        return False, None

    def release(self):
        if self._sock:
            self._sock.close()
        self._proc.terminate()
        subprocess.run(self._unforward, capture_output=True)


class Camera:
    def __init__(self, source="0", size=(1920, 1080)):
        self.source = str(source)
        self._lock = threading.Lock()
        self._frame, self._time, self._count = None, 0.0, 0
        self._file_fps = 0
        if self.source.startswith("android"):
            self._cap = PhoneStream(self.source.partition(":")[2], size)
        elif self.source.isdigit():
            self._cap = cv2.VideoCapture(int(self.source))
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, size[0])
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        else:
            self._cap = cv2.VideoCapture(self.source)
            if Path(self.source).exists():  # recorded video: play at its own speed, looped
                self._file_fps = self._cap.get(cv2.CAP_PROP_FPS) or 30
        if not self._cap.isOpened():
            self._cap.release()
            raise RuntimeError(f"cannot open camera {self.source!r}")
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while self._running:
            ok, frame = self._cap.read()
            now = time.monotonic()
            if not ok:
                if self._file_fps:
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                else:
                    time.sleep(0.01)
                continue
            with self._lock:
                self._frame, self._time, self._count = frame, now, self._count + 1
            if self._file_fps:
                time.sleep(1 / self._file_fps)

    def read(self, newer_than=0, timeout=2.0):
        """Return (frame, capture_time, frame_number) of the newest frame, waiting
        until its number exceeds `newer_than`. Returns (None, 0, 0) on timeout."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self._lock:
                if self._frame is not None and self._count > newer_than:
                    return self._frame, self._time, self._count
            time.sleep(0.002)
        return None, 0.0, 0

    def close(self):
        self._running = False
        self._thread.join(timeout=2)
        self._cap.release()


if __name__ == "__main__":  # self-check: python -m visiontouch.camera [source] [image-out]
    import sys

    cam = Camera(sys.argv[1] if len(sys.argv) > 1 else "0")
    try:
        frame, t0, n0 = cam.read(timeout=10)
        assert frame is not None, "no frame"
        time.sleep(3)
        frame, t1, n1 = cam.read()
        print(f"{cam.source}: {frame.shape[1]}x{frame.shape[0]}, {(n1 - n0) / (t1 - t0):.1f} fps")
        if len(sys.argv) > 2:
            cv2.imwrite(sys.argv[2], frame)
    finally:
        cam.close()
