import platform
import shutil
import subprocess
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

packaging = Path(SPECPATH).resolve()
root = packaging.parent
mac = sys.platform == "darwin"
windows = sys.platform == "win32"
linux = sys.platform.startswith("linux")
machine = platform.machine().lower()
if not (
    (mac and machine == "arm64")
    or ((windows or linux) and machine in {"amd64", "x86_64"})
):
    raise SystemExit(f"Unsupported build host: {sys.platform} {machine}")

# PyInstaller's hooks collect OpenCV, PyAV and pywebview's platform resources.
analysis = Analysis(
    [str(root / "visiontouch" / "__main__.py")],
    pathex=[str(root)],
    binaries=collect_dynamic_libs("mediapipe"),
    datas=[
        (str(root / "web" / "dist"), "web/dist"),
        (str(root / "visiontouch" / "models" / "hand_landmarker.task"), "visiontouch/models"),
        *collect_data_files("mediapipe"),
    ],
    hiddenimports=["webview.platforms.edgechromium"] if windows else [],
    excludes=["pytest", "tkinter"] + (["webview"] if linux else []),
)
exe = EXE(
    PYZ(analysis.pure),
    analysis.scripts,
    exclude_binaries=True,
    name="VisionTouch",
    console=linux,
    icon=str(packaging / "visiontouch.ico") if windows else None,
    target_arch="arm64" if mac else None,
    upx=False,
)
folder = COLLECT(exe, analysis.binaries, analysis.datas, name="VisionTouch", upx=False)

dist = Path(DISTPATH)
if mac:
    app = BUNDLE(
        folder,
        name="VisionTouch.app",
        icon=str(packaging / "visiontouch.icns"),
        bundle_identifier="org.visiontouch.desktop",
        info_plist={
            "NSCameraUsageDescription": "VisionTouch uses the camera to detect touch on the projected surface.",
        },
    )
    bundle = dist / "VisionTouch.app"
    subprocess.run(["codesign", "--verify", "--deep", "--strict", bundle], check=True)
    archive = dist / "VisionTouch-macos-arm64.zip"
    archive.unlink(missing_ok=True)
    subprocess.run(["ditto", "-c", "-k", "--keepParent", bundle, archive], check=True)
elif windows:
    shutil.make_archive(dist / "VisionTouch-windows-x64", "zip", dist, "VisionTouch")
else:
    shutil.make_archive(dist / "VisionTouch-linux-x64", "gztar", dist, "VisionTouch")
