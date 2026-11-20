# VisionTouch desktop builds

| Platform | Release archive | Entry point |
| --- | --- | --- |
| macOS 15 or later, Apple silicon | `VisionTouch-macos-arm64.zip` | `VisionTouch.app` |
| Windows x64 | `VisionTouch-windows-x64.zip` | `VisionTouch\VisionTouch.exe` |
| Linux x64 | `VisionTouch-linux-x64.tar.gz` | `VisionTouch/VisionTouch` |

Extract the archive and keep the application and its bundled files together. MediaPipe has no Intel macOS wheel, so there is no Intel macOS build.

## First launch

- **macOS** — The app is signed ad hoc. A downloaded copy can trigger Gatekeeper because it has no Developer ID signature or notarization. If you trust the download, try opening it, then select **System Settings → Privacy & Security → Open Anyway** and confirm. [Apple's Gatekeeper instructions](https://support.apple.com/en-us/102445)
  - **Camera** lets VisionTouch see the projected surface and your hand.
  - **Screen & System Audio Recording** lets VisionTouch capture the displayed image so it can distinguish hands from the projection. VisionTouch captures the screen image only.
  - **Accessibility** lets VisionTouch move and click the OS pointer when you enable mouse control. You may need to enable this manually in **Privacy & Security**. Restart VisionTouch if macOS asks you to do so after granting access.
- **Windows** — Run `VisionTouch.exe` from the extracted folder. The window uses the Microsoft Edge WebView2 Evergreen Runtime. If it is missing, install the x64 runtime before launching. [Microsoft's WebView2 download](https://developer.microsoft.com/en-us/microsoft-edge/webview2/#download)
- **Linux** — Run `./VisionTouch/VisionTouch` from a terminal. The bundle omits the pywebview GUI toolkits, so it opens the stage in your default browser via `xdg-open`. Move the browser to the projector display, enter fullscreen if desired, and keep the VisionTouch process running. Use an X11 desktop session for screen capture and mouse control. Native Wayland capture and mouse control are unsupported. Ubuntu 24.04 is the build baseline. On a minimal Ubuntu system, install `xdg-utils`, `libegl1`, `libgles2`, `libx11-6`, `libxcb1`, `libxcb-randr0`, `libxcb-render0`, `libxcb-shm0`, and `libxcb-xfixes0`.

The Android USB camera option requires `adb` and `scrcpy` on `PATH` plus their scrcpy server file. Set `SCRCPY_SERVER_PATH` if the app cannot locate that file.

## Build locally

Build on the target OS and architecture. Use a current uv, its managed Python 3.14.8, Node.js 24, and pnpm 12.8.1. From the repository root, run:

```sh
cd web
pnpm install --frozen-lockfile
pnpm build
cd ..
uv sync --locked --no-dev --managed-python --python 3.14.8
uv pip install -r packaging/requirements.txt
```

On Linux, also install MediaPipe's native libraries and replace the standard OpenCV wheel with the same-version headless build. MediaPipe declares the standard wheel as a dependency, so use `--no-sync` for the subsequent commands to preserve the replacement.

```sh
sudo apt-get update
sudo apt-get install -y --no-install-recommends libegl1 libgles2
uv pip uninstall opencv-contrib-python
uv pip install -r packaging/requirements-linux.txt --no-deps --only-binary :all:
```

Build and archive:

```sh
uv run --no-sync pyinstaller --noconfirm --distpath packaging/dist --workpath packaging/build packaging/VisionTouch.spec
```

The bundle and archive are written to `packaging/dist/`. The macOS and Windows icons are derived from `web/public/icon.svg`. On Linux, the browser stage uses that SVG directly.

Run the headless check for your OS. It serves the built stage on a free loopback port, runs the hand-landmark model on a blank image, and initializes the H.264 decoder.

```sh
# macOS
packaging/dist/VisionTouch.app/Contents/MacOS/VisionTouch --check

# Linux
packaging/dist/VisionTouch/VisionTouch --check
```

```powershell
# Windows PowerShell
$process = Start-Process -FilePath ./packaging/dist/VisionTouch/VisionTouch.exe -ArgumentList '--check', '--check-log', 'visiontouch-check.log' -Wait -PassThru
Get-Content visiontouch-check.log
$process.ExitCode
```

## Releases and verification

Push a `v*` tag to run all three builds and publish a GitHub Release with the archives.. Pull requests and manual dispatch run the build and upload job artifacts without publishing a release. Each file keeps the name in the table, so it can be downloaded at `https://github.com/<owner>/<repo>/releases/latest/download/<archive>`. Private repositories require repository access to download assets.

Before freezing, CI also runs `tests/test_simulated_rig.py` and the self-checks of the engine modules. Verification for the Windows and Linux packages is otherwise limited to CI's headless self-check (`--check`). Neither package has been run against a real projector and camera. The macOS bundle has been checked headlessly on Apple silicon. Normal launch, permission dialogs, and hardware use still need a separate test. OpenCV and PyAV ship separate copies of FFmpeg on macOS, so loading both can emit duplicate Objective-C class warnings. The headless check verifies decoder initialization. Android streaming and camera capture still need hardware verification.
