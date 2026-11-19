# VisionTouch stage (`web/`)

Everything that gets projected: launcher, apps, calibration patterns, debug view.
Vite + TypeScript, plain DOM and Canvas 2D, `pdfjs-dist` as the only runtime dependency.
The contract with the Python engine is [`../docs/protocol.md`](../docs/protocol.md).

```sh
pnpm install
pnpm build              # type-check + static site in dist/ (no CDN, works offline)
pnpm test               # unit tests (warp maths, pointer shim)
pnpm e2e                # headless Chromium + WebKit against dist/ (run pnpm build first)
pnpm dev                # dev server on http://localhost:5199 (mouse only, no engine)
node fake-engine.mjs --port 5198 --demo   # pretend engine: circling hand, pattern, warp
```

## Map

| File | What it does |
| --- | --- |
| `src/main.ts` | Shell: content box + keystone warp (black outside it), pattern overlay, app switching (`#board` in the URL), hold-to-go-home, touch feedback, desktop-mode strip, calibration toast |
| `src/engine.ts` | The WebSocket: `on(type, fn)`, `send(msg)`, `engine.state` |
| `src/warp.ts` | Homography maths: CSS `matrix3d`, inverse, `contentPoint(event)` |
| `src/pointers.ts` | Turns `pointers` messages into DOM PointerEvents; `hands`, `poseOf`, `onGesture`; cursor rings with dwell-click progress |
| `src/ui.ts` | The `App` interface, palette, small helpers (dialog, burst, canvas sizing, loop) |
| `src/ink.ts` | Smoothed freehand strokes (Board, Slides) |
| `src/apps/*.ts` | One file per app; `apps/index.ts` lists them and holds the launcher |
| `src/quiz.json` | Quiz questions |
| `public/sample-deck.pdf` | Built-in deck for Slides (`node scripts/make-sample-deck.mjs` regenerates it) |

## Writing an app

An app is `{ id, title, blurb, color, icon, mount(root) }`. `mount` builds the app inside `root`
and returns a cleanup function. Listen to ordinary pointer events; a hand and a mouse look the
same. Use `contentPoint(e)` for coordinates and `poseOf(e.pointerId)` if you care about the pose.
Add it to the list in `src/apps/index.ts`.

Design rules come from the physics: light backgrounds, thick outlines, big type and targets
(1rem = 1/36 of the window height), no large moving areas, and no large saturated or dark
fills. The projector shows red, green and blue in turn and the camera's rolling shutter turns
a big strong colour into bands that look like a hand, so anything bigger than about 4rem x 4rem
is a light tint and the strong colour goes to outlines, icon chips and small accents.
`e2e/colours.spec.ts` fails if a screen has a solid saturated or dark block of 130 x 130 px
at 1920x1080 (thresholds at the top of that file). Game sprites are small and stay saturated.

The fake engine also takes `POST /save/<name>.png`, follows the `mode` and `keystone` commands,
and can serve test pipeline streams (see the top of `fake-engine.mjs`).
