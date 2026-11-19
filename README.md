# VisionTouch: Smart Projector Board

Turn any projector into a touch board with one ordinary camera: a laptop webcam, a phone, or a USB webcam. VisionTouch knows what it is projecting, predicts what the camera should see, and treats whatever differs as your hand. Point to move, hold still or pinch to click, open your palm to erase, swipe to change slides.

<!-- Hero picture: add a photo of the board in use here, e.g. ![VisionTouch in use](docs/figures/hero.jpg) -->

A Digital Image Processing course project. How it works, stage by stage: [docs/how-it-works.md](docs/how-it-works.md). Full report with measurements: [docs/report.md](docs/report.md).

## Quick start

You need Python with [uv](https://docs.astral.sh/uv/), Node.js with [pnpm](https://pnpm.io/), a projector showing your computer's screen (mirrored or as the main display), and a camera that can see the whole projected picture.

```sh
uv sync
cd web && pnpm install && pnpm build && cd ..
uv run python -m visiontouch
```

This opens the projected stage full-screen and starts the camera. Useful options:

| Option | Effect |
|---|---|
| `--camera 1` | Use another camera (the number the operating system gives it). |
| `--camera android` | Use an Android phone's back camera over USB (see below). |
| `--windowed` | Do not go full-screen. |
| `--browser` | Show the stage in your web browser instead of the built-in window. |
| `--no-landmarks` | Classical detection only, without MediaPipe (no pinch or palm). |
| `--check` | Check the installation without opening a window or camera. |

Ready-made desktop builds are described in [packaging/README.md](packaging/README.md).

## Aim the camera and calibrate

1. Place the camera so it sees the **whole projected picture**, with a little margin around it. Below or beside the projector works. A steep angle works but lowers accuracy.
2. Keep the camera **still**. If it moves, calibrate again.
3. Open **Settings** and press **Calibrate now**. The projector shows a grid of black-and-white markers, a few colour mosaics, and a black and a white flash. Stay out of the picture for about five seconds.
4. The status line reports the number of markers found, the alignment error and the camera delay. If calibration fails, the camera probably cannot see the whole picture.

Calibration also straightens the picture automatically (keystone correction) if the camera can see the edge of the projection screen. You can switch this off in Settings.

## Using a phone as the camera

- **Android, over USB.** Needs Android 12 or later, [scrcpy](https://github.com/Genymobile/scrcpy) and `adb` installed, and USB debugging switched on. Start with `--camera android` (or `--camera android:SERIAL` if several phones are connected). Only the phone's back camera is used; its screen is left alone. If the scrcpy server file is not found, set `SCRCPY_SERVER_PATH`.
- **iPhone, through Continuity Camera** (macOS). The iPhone appears as an ordinary camera. Start with `--camera 1` (or the next number) and pick the one that shows the iPhone's view.
- **Any webcam** works as a numbered camera.

Put the phone on a stand: it must not move after calibration.

## The apps

| App | What it does |
|---|---|
| Board | Draw with your finger. Open your palm to erase. |
| Balloons | Pop as many as you can. |
| Catch | Catch the stars, avoid the bombs. |
| Slides | Present any PDF; swipe or tap the edges to change pages, draw on the page. |
| Quiz | Questions on image processing basics. |
| Memory | Find the six pairs. |
| Accuracy | Tap 20 targets; measures how precisely touches land. |
| Pipeline | Watch each processing step live. |
| Settings | Calibrate, keystone, apps or desktop mode, camera. |

**Desktop mode** (in Settings) moves the computer's real mouse instead, so you can use any program. A small strip with a "back to apps" button stays on top. To go home from any app, hold the home button for one second.

## Gestures

| Gesture | Action |
|---|---|
| Point with one finger | Move the pointer. |
| Hold the finger still (about 0.8 s) | Click. |
| Pinch thumb and index finger | Press (hold the pinch to drag). |
| Open palm | Erase (Board). |
| Fast sideways swipe | Next or previous slide. |

## Limits

- **Measured on synthetic hands only, so far.** Our tests paint a hand shape into the projected picture and film it through the real projector and camera. Real skin, real 3-D shadows, pinch on a real hand and a body blocking the camera have not been measured yet. The real-hand test with the Accuracy app is still to be done.
- **Busy or dark content is hard.** Photos and cluttered desktops cause false detections; a hand over pure black is invisible to the camera method; dense text breaks the hand's outline. Plain backgrounds, slides, drawings and games work best.
- **No true touch.** One camera cannot measure depth, so a click is a pause or a pinch, not contact with the wall.
- **Delay.** The camera and projector add a noticeable delay; the pointer predicts a little ahead to hide part of it.
- **One camera position.** Moving the camera or the projector needs a new calibration.

The measured numbers are in [docs/report.md](docs/report.md).

## Running the evaluation

The offline experiments use the recorded dataset in `runs/ds1` and `runs/ds1b` (not included in the repository) and never open a camera or a window.

```sh
uv sync --group docs
uv run python -m eval.experiments    # about two minutes; writes runs/figures/results.json
uv run python -m eval.figures        # figures in runs/figures/ and docs/figures/
uv run python -m eval.fill_report    # refreshes the tables in docs/report.md and docs/how-it-works.md
uv run python docs/slides/build.py   # the presentation, docs/slides/VisionTouch.pptx
```

The rig tests (`python -m eval.live_test`, `eval.idle_test`, `eval.keystone_test`, `eval.capture_dataset`) project test pictures full-screen and need the projector and camera. After a session with the Accuracy app, `eval.fill_report` adds the real-hand numbers from `~/.visiontouch/log.jsonl`.

## Project layout

| Folder | Contents |
|---|---|
| `visiontouch/` | The engine (Python, OpenCV, NumPy, MediaPipe): camera, calibration, prediction, hand finding, tracking. |
| `web/` | The projected stage and apps (TypeScript). See [web/README.md](web/README.md). |
| `eval/` | Dataset capture, rig tests, offline experiments, figures. |
| `docs/` | How it works, report, related work, engine protocol, slides. |

## Licence

MIT (licence file to be added by the team) — [Copyright holders: team names].

The hand landmark model `visiontouch/models/hand_landmarker.task` is from Google's [MediaPipe](https://github.com/google-ai-edge/mediapipe) and is distributed under the Apache License 2.0. MediaPipe itself is also Apache-2.0.
