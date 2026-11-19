// Accuracy test: the project's evaluation numbers. 20 targets on a 5x4 grid (corners included)
// in random order; for each tap we log target, hit, error and time-to-hit to the engine.
import { send } from '../engine'
import { contentPoint } from '../warp'
import { C, dialog, fitCanvas, html, loop, shuffle, type App } from '../ui'

const COLS = 5, ROWS = 4
// Grid spans 10%..90% of the width and 12%..88% of the height, clear of the home button.
const gx = (i: number) => 0.1 + (0.8 * i) / (COLS - 1)
const gy = (j: number) => 0.12 + (0.76 * j) / (ROWS - 1)
const TARGET_R = 44

interface Result { tx: number; ty: number; hx: number; hy: number; err: number; ms: number }

export const accuracy: App = {
  id: 'accuracy',
  title: 'Accuracy',
  blurb: 'Measure touch precision.',
  color: C.white,
  icon: '<svg viewBox="0 0 64 64"><circle cx="32" cy="32" r="24"/><circle cx="32" cy="32" r="12"/><circle cx="32" cy="32" r="2"/></svg>',

  mount(root) {
    root.append(html('<canvas class="full"></canvas>'), html('<div class="hud"></div>'))
    const canvas = root.querySelector('canvas')!
    const hud = root.querySelector<HTMLElement>('.hud')!
    const { ctx, w, h } = fitCanvas(canvas)
    let targets: { x: number; y: number }[] = []
    let results: Result[] = [], shownAt = 0, last: Result | null = null, running = false
    const session = new Date().toISOString()

    function intro() {
      dialog(root, {
        title: 'Accuracy test',
        body: `Tap the centre of each target as precisely as you can.<br>${COLS * ROWS} targets, one at a time.`,
        actions: [{ label: 'Start', color: C.mint, onTap: start }],
      })
    }
    function start() {
      targets = []
      for (let i = 0; i < COLS; i++) for (let j = 0; j < ROWS; j++) targets.push({ x: gx(i) * w, y: gy(j) * h })
      shuffle(targets)
      results = []
      last = null
      running = true
      shownAt = performance.now()
    }

    canvas.addEventListener('pointerdown', (e) => {
      if (!running) return
      const now = performance.now()
      if (now - shownAt < 250) return // ignore a double tap carried over from the previous target
      const t = targets[results.length], p = contentPoint(e)
      const r: Result = { tx: t.x, ty: t.y, hx: p.x, hy: p.y, err: Math.hypot(p.x - t.x, p.y - t.y), ms: now - shownAt }
      results.push(r)
      last = r
      send({
        t: 'log',
        name: 'accuracy',
        data: {
          session,
          index: results.length - 1,
          input: e.pointerType,
          w, h,
          target_x: t.x / w, target_y: t.y / h, // normalised, like protocol pointers
          hit_x: p.x / w, hit_y: p.y / h,
          error_px: +r.err.toFixed(1),
          error_pct_width: +((100 * r.err) / w).toFixed(3),
          time_ms: Math.round(r.ms),
        },
      })
      shownAt = now
      if (results.length === targets.length) {
        running = false
        summary()
      }
    })

    function summary() {
      const errs = results.map((r) => (100 * r.err) / w)
      const mean = errs.reduce((a, b) => a + b, 0) / errs.length
      const max = Math.max(...errs)
      const time = results.reduce((a, r) => a + r.ms, 0) / results.length / 1000
      dialog(root, {
        title: 'Results',
        body: `<div class="acc-summary">
            <dl>
              <dt>Mean error</dt><dd>${mean.toFixed(2)}<small>% of width</small></dd>
              <dt>Max error</dt><dd>${max.toFixed(2)}<small>% of width</small></dd>
              <dt>Mean time</dt><dd>${time.toFixed(2)}<small>s per target</small></dd>
            </dl>
            <canvas class="acc-scatter"></canvas>
          </div>`,
        actions: [{ label: 'Run again', color: C.mint, onTap: start }],
      })
      drawScatter(root.querySelector<HTMLCanvasElement>('.acc-scatter')!, results, w)
    }

    const stop = loop((_, now) => {
      hud.innerHTML = running ? `<span class="pill">Target ${results.length + 1} / ${targets.length}</span>` : ''
      ctx.fillStyle = C.paper
      ctx.fillRect(0, 0, w, h)
      if (last && now - shownAt < 500) {
        // brief feedback: where the tap landed relative to the previous target
        ctx.strokeStyle = C.tomato
        ctx.lineWidth = 6
        ctx.beginPath()
        ctx.moveTo(last.tx, last.ty)
        ctx.lineTo(last.hx, last.hy)
        ctx.stroke()
        dot(ctx, last.hx, last.hy, 12, C.tomato)
      }
      if (running) {
        const t = targets[results.length]
        const pulse = 1 + 0.08 * Math.sin(now / 160)
        ring(ctx, t.x, t.y, TARGET_R * 2.2 * pulse, C.cobalt, 8)
        ring(ctx, t.x, t.y, TARGET_R, C.tomato, 12)
        dot(ctx, t.x, t.y, 9, C.ink)
      }
    })
    intro()
    return stop
  },
}

const ring = (ctx: CanvasRenderingContext2D, x: number, y: number, r: number, c: string, lw: number) => {
  ctx.strokeStyle = c
  ctx.lineWidth = lw
  ctx.beginPath()
  ctx.arc(x, y, r, 0, Math.PI * 2)
  ctx.stroke()
}
const dot = (ctx: CanvasRenderingContext2D, x: number, y: number, r: number, c: string) => {
  ctx.fillStyle = c
  ctx.beginPath()
  ctx.arc(x, y, r, 0, Math.PI * 2)
  ctx.fill()
}

/** Error vectors (hit - target) around a crosshair, with rings at 1%, 2% and 3% of the width. */
function drawScatter(canvas: HTMLCanvasElement, results: Result[], width: number) {
  const { ctx, w, h } = fitCanvas(canvas)
  const cx = w / 2, cy = h / 2
  const maxPct = Math.max(3, ...results.map((r) => Math.ceil((100 * r.err) / width)))
  const scale = (Math.min(w, h) / 2 - 16) / maxPct // canvas px per 1% of width
  ctx.fillStyle = C.white
  ctx.fillRect(0, 0, w, h)
  ctx.font = '700 22px "Atkinson Hyperlegible"'
  for (let pct = 1; pct <= maxPct; pct++) {
    ring(ctx, cx, cy, pct * scale, pct % 2 ? C.sky : C.cobalt, 3)
    ctx.fillStyle = C.cobalt
    ctx.fillText(`${pct}%`, cx + pct * scale * 0.71 + 4, cy - pct * scale * 0.71 - 4)
  }
  ctx.strokeStyle = C.ink
  ctx.lineWidth = 3
  ctx.beginPath()
  ctx.moveTo(cx, 8)
  ctx.lineTo(cx, h - 8)
  ctx.moveTo(8, cy)
  ctx.lineTo(w - 8, cy)
  ctx.stroke()
  for (const r of results) {
    const k = (100 / width) * scale
    dot(ctx, cx + (r.hx - r.tx) * k, cy + (r.hy - r.ty) * k, 10, C.tomato)
  }
}
