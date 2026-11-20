# Engine ↔ stage protocol

VisionTouch has two halves:

- **Engine** (`visiontouch/`, Python): camera, calibration, hand detection, OS mouse.
- **Stage** (`web/`, TypeScript): everything that is projected — launcher, apps, calibration patterns, debug view.

The engine serves the built stage (`web/dist`) at `http://127.0.0.1:8765/` and talks to it over one WebSocket at `/ws`. Messages are JSON text; `t` is the message type.

## Coordinates

Pointer positions are normalised to the stage **content box**: `x, y ∈ [0, 1]`, origin top-left. The content box is the element the keystone warp is applied to, so apps never need to know about the warp.

## Engine → stage

| Message | Meaning |
| --- | --- |
| `{"t":"pointers","p":[{"id":1,"x":0.42,"y":0.31,"down":false,"pose":"point"}]}` | Sent every camera frame (about 30/s). One entry per tracked hand; an empty list means no hands. A hand appears only after 3 detections in a row. `down` is the press state: a pinch, a short dwell tap, or, in `hold` dwell mode, a press that lasts until the next hold. `pose` is `point`, `pinch`, `palm` or `fist`. |
| `{"t":"gesture","name":"swipe_left"}` | One-shot gesture: `swipe_left`, `swipe_right`. |
| `{"t":"mask","w":128,"h":72,"b64":"..."}` | Silhouette of everything in front of the screen, row-major, one byte per cell (0 or 255), base64. The grid covers the content box, like pointer coordinates. Sent every camera frame after `subscribe_mask`. |
| `{"t":"pattern","id":7,"url":"/pattern/7.png"}` | Show this image stretched to the full window, unwarped, on top of everything. `url: null` removes it. Used for calibration. |
| `{"t":"warp","m":[9 numbers]}` | Row-major 3×3 homography mapping content-box pixels to window pixels (keystone correction). `m: null` means identity. |
| `{"t":"state","calibrated":true,"camera":"MacBook","fps":29.8,"latency_ms":110,"mode":"apps","keystone":true,"sensitivity":1.0,"dwell":"tap","message":""}` | Engine status, sent on change and once a second. |

## Stage → engine

| Message | Meaning |
| --- | --- |
| `{"t":"hello","w":1920,"h":1080}` | Sent on connect and on resize: window size in CSS pixels. |
| `{"t":"pattern_shown","id":7}` | The pattern with this id has been painted (send after two animation frames). |
| `{"t":"cmd","name":"calibrate"}` | Run calibration. |
| `{"t":"cmd","name":"mode","value":"apps"}` | `apps`: pointers drive the stage. `desktop`: pointers drive the OS mouse; the engine shrinks the stage window to a small always-on-top strip and the stage shows only a "back to apps" button in it. |
| `{"t":"cmd","name":"subscribe_mask","value":true}` | Start or stop mask messages. |
| `{"t":"cmd","name":"keystone","value":true}` | Turn automatic keystone correction on or off (the engine answers with a `warp`). |
| `{"t":"cmd","name":"dwell","value":"hold"}` | What holding the pointing finger still does. `tap` (default): one short press, for buttons. `hold`: press and stay pressed until the next hold or until the hand leaves, for drawing without a pinch. The Board sends `hold` while a hand is over its canvas, and `tap` over its toolbar and when it closes. |
| `{"t":"cmd","name":"sensitivity","value":1.0}` | Detection sensitivity, 0.4 to 2.5 (1 is the default). Higher finds fainter hands and risks more false alarms; useful with weak projectors. Reported back in `state.sensitivity`. |
| `{"t":"cmd","name":"camera","value":"0"}` | Switch camera source. |
| `{"t":"log","name":"accuracy","data":{...}}` | Append a record to the engine's run log (used by the accuracy test app). |

## Debug images

`GET /debug/<stage>.mjpg` streams a pipeline stage as MJPEG, usable directly as an `<img src>`. Stages: `camera`, `predicted`, `residual`, `mask`, `overlay`. `GET /debug/stages` returns a JSON array of these five names. The engine makes the images only while at least one stream is open.

## Saving files

`POST /save/<name>.png` with the PNG bytes as the body stores the picture in the user's `Pictures/VisionTouch` folder and answers `{"path": "..."}`. The built-in window cannot download files, so the Board uses this to save.

## How apps receive touches

The stage turns `pointers` messages into ordinary DOM `PointerEvent`s (`pointerdown`, `pointermove`, `pointerup`, plus `click`), dispatched on the element under the pointer. Apps are written against pointer events only, so a mouse works the same way with no engine running.
