# VisionTouch: Smart Projector Board

Turn any projector into a touch board with one ordinary camera: a laptop webcam, a phone, or a USB webcam. VisionTouch knows what it is projecting, predicts what the camera should see, and looks for your hand only in whatever differs. Point to move, hold still to click, swipe to change slides. With a camera close enough to see your fingers clearly, pinch also clicks and an open palm erases.

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
| `--port 8766` | Port of the local stage server (default 8765). |
| `--windowed` | Do not go full-screen. |
| `--browser` | Show the stage in your web browser instead of the built-in window. |
| `--no-landmarks` | Classical detection only, without MediaPipe (no pinch or palm). It expects a bare arm reaching in from the side, not a person standing in the picture. |
| `--record FOLDER` | Save the session (camera frames and screen pictures) so it can be replayed offline with `python -m eval.replay FOLDER`. |
| `--check` | Check the installation without opening a window or camera. `--check-log FILE` writes the result to a file. |

Ready-made desktop builds are described in [packaging/README.md](packaging/README.md).

## Aim the camera and calibrate

1. Place the camera so it sees the **whole projected picture**, with a little margin around it. Below or beside the projector works. A steep angle works but lowers accuracy.
2. Keep the camera **still**. If it moves, the engine notices and calibrates again by itself.
3. Open **Settings** and press **Calibrate now**. The projector shows a grid of black-and-white markers, a few colour mosaics, and a black and a white flash. Stay out of the picture for about ten seconds. Calibration needs Apps mode (not Desktop mode). The engine also calibrates on first start and recalibrates by itself if the camera or projector is knocked.
4. The status line reports the number of markers found, the alignment error and the camera delay. If calibration fails, the camera probably cannot see the whole picture.

Calibration also straightens the picture automatically (keystone correction). It squares the picture to the edge of the projection screen if the camera can see it, and to the camera's own view if not. You can switch this off in Settings. If the camera stops sending pictures, the engine reopens it.

## Using a phone as the camera

- **Android, over USB.** Needs Android 12 or later, [scrcpy](https://github.com/Genymobile/scrcpy) and `adb` installed, and USB debugging switched on. Start with `--camera android` (or `--camera android:SERIAL` if several phones are connected). Only the phone's back camera is used; its screen is left alone. If the scrcpy server file is not found, set `SCRCPY_SERVER_PATH`.
- **iPhone, through Continuity Camera** (macOS). The iPhone appears as an ordinary camera. Start with `--camera 1` (or the next number) and pick the one that shows the iPhone's view.
- **Any webcam** works as a numbered camera.

Put the phone on a stand: it must not move after calibration.

## The apps

| App | What it does |
|---|---|
| Board | Draw with your finger (blue by default): hold still to start a stroke and again to end it. Erase with the Eraser button or an open palm. |
| Balloons | Touch balloons to pop as many as you can. |
| Catch | Catch the stars, avoid the bombs. |
| Slides | Present any PDF; swipe or tap the edges to change pages, draw on the page. |
| Quiz | Questions on image processing basics. |
| Memory | Find the six pairs. |
| Accuracy | Tap 20 targets; measures how precisely touches land. |
| Pipeline | Watch each processing step live. |
| Settings | Calibrate, keystone, apps or desktop mode, detection sensitivity, camera. |

**Desktop mode** (in Settings) moves the computer's real mouse instead, so you can use any program. The window shrinks to a small strip with a "back to apps" button that stays on top. To go home from any app, point at the home button in the bottom-right corner for one second. A hand does not need to press it; a mouse must keep pressing.

## Gestures

| Gesture | Action |
|---|---|
| Point with one finger | Move the pointer. |
| Hold the hand still (about 0.8 s) | Click. The cursor ring fills up while you wait. |
| On the Board: hold still, move, hold still again | Draw a stroke without pinching. |
| Pinch thumb and index finger | Press (hold the pinch to drag). Needs a large hand in the camera, see Limits. |
| Open palm | Erase (Board). Needs a large hand in the camera, see Limits. |
| Fast sideways swipe | Next or previous slide. |
| Point at a balloon | Pops it. No press needed. |
| Point at the home button for 1 s | Go home. No press needed. |

## Limits

- **Mostly measured on synthetic hands.** Most tests paint a hand shape into the projected picture and film it through the real projector and camera. Real-hand results so far come from one person, one laptop camera and one room: a median error of 2.3 % of the screen width over 21 taps in the Accuracy app.
- **Reach sideways or upwards.** The camera stands behind you, so it cannot see a hand held in front of your own body.
- **Pinch and palm need a large hand in the camera.** With a laptop camera a few metres from the screen the hand is too small for its pose to be read reliably, so those two gestures switch themselves off and you click by holding still. A phone camera nearer the screen brings them back.
- **Busy or dark content is hard.** Photos and cluttered desktops cause false detections; dense text breaks the hand's outline. Plain backgrounds, slides, drawings and games work best.
- **A hand is invisible over anything dark.** No light falls on it there, so the camera sees no change. The apps are drawn to suit this: the cursor ring is bright with no dark outline, the Board draws in blue, game sprites are outlined in a darker shade of their own colour, and large areas are light tints.
- **Windows and Linux are untested on real hardware.** Their builds have only passed the automated headless self-check. The macOS build has been checked headlessly on Apple silicon. See [packaging/README.md](packaging/README.md).
- **No true touch.** One camera cannot measure depth, so a click is a pause or a pinch, not contact with the wall.
- **Delay.** The camera and projector add a noticeable delay; the pointer predicts a little ahead to hide part of it.
- **One camera position.** The camera and projector must stay put. After a knock the engine notices within a few seconds and calibrates again by itself, which interrupts the picture for about ten seconds.

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

The rig tests (`python -m eval.live_test`, `eval.idle_test`, `eval.soak_test`, `eval.keystone_test`, `eval.stage_test`, `eval.capture_dataset`) open a full-screen window and need the projector and camera. After a session with the Accuracy app, `eval.fill_report` adds the real-hand numbers from `~/.visiontouch/log.jsonl`.

The tests in `tests/` need no hardware. `uv run python tests/test_simulated_rig.py` runs the whole engine against a simulated projector and camera (with a 0.2 s display delay) and checks four cases: calibrate and find a fingertip, reaching over the launcher, the app's own feedback (cursor ring and ink), and sprites drifting behind the hand. `cd web && pnpm test` runs the stage's unit tests.

## Project layout

| Folder | Contents |
|---|---|
| `visiontouch/` | The engine (Python, OpenCV, NumPy, MediaPipe): camera, calibration, prediction, hand finding, tracking. |
| `web/` | The projected stage and apps (TypeScript). See [web/README.md](web/README.md). |
| `eval/` | Dataset capture, rig tests, session replay, offline experiments, figures. |
| `tests/` | Engine tests against a simulated projector and camera. |
| `docs/` | How it works, report, related work, engine protocol, slides. |

## Licence

MIT, see [LICENSE](LICENSE).

The hand landmark model `visiontouch/models/hand_landmarker.task` is from Google's [MediaPipe](https://github.com/google-ai-edge/mediapipe) and is distributed under the Apache License 2.0. MediaPipe itself is also Apache-2.0.
