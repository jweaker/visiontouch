// Catch: falling stars are good, spiky bombs are bad. Catch with your hands (pointers) or,
// when the engine sends the silhouette mask, with your arms and whole body.
import { on, send } from '../engine'
import { hands } from '../pointers'
import { contentPoint, toWindow } from '../warp'
import { C, burst, clock, dialog, fitCanvas, html, loop, type App, darker } from '../ui'

const LEVELS = [
  { name: 'Easy', speed: 220, every: 0.85, bad: 0.2 },
  { name: 'Normal', speed: 320, every: 0.6, bad: 0.3 },
  { name: 'Hard', speed: 440, every: 0.42, bad: 0.38 },
]
const ROUND_S = 60
const CATCH_R = 90 // reach of a hand, content pixels
const ITEM_R = 46
const GOOD = [C.sun, C.mint, C.sky, C.pink]

interface Item { x: number; y: number; vy: number; bad: boolean; color: string; spin: number }

export const catchGame: App = {
  id: 'catch',
  title: 'Catch',
  blurb: 'Stars yes, bombs no.',
  color: C.mint,
  icon: '<svg viewBox="0 0 64 64"><path d="M10 36c4 16 40 16 44 0z"/><circle cx="24" cy="14" r="5"/><circle cx="42" cy="22" r="5"/></svg>',

  mount(root) {
    root.append(html('<canvas class="full"></canvas>'), html('<div class="hud"></div>'))
    const canvas = root.querySelector('canvas')!
    const hud = root.querySelector<HTMLElement>('.hud')!
    const { ctx, w, h } = fitCanvas(canvas)
    let items: Item[] = []
    let level = LEVELS[0], score = 0, lives = 3, left = 0, spawn = 0, playing = false

    // Mouse position (hands come from the shim's `hands` map instead).
    let mouse: { x: number; y: number } | null = null
    canvas.addEventListener('pointermove', (e) => {
      if (e.pointerType !== 'touch') mouse = contentPoint(e)
    })
    canvas.addEventListener('pointerleave', () => (mouse = null))

    // Silhouette mask: a small grid (e.g. 64x36) of 0/255 covering the content box.
    let mask: { w: number; h: number; cells: Uint8Array; at: number } | null = null
    const maskCanvas = document.createElement('canvas')
    send({ t: 'cmd', name: 'subscribe_mask', value: true })
    const offMask = on('mask', (m) => {
      const cells = Uint8Array.from(atob(m.b64), (c) => c.charCodeAt(0))
      mask = { w: m.w, h: m.h, cells, at: performance.now() }
      // Paint it as a soft mint shadow so players see what the camera sees.
      maskCanvas.width = m.w
      maskCanvas.height = m.h
      const img = new ImageData(m.w, m.h)
      cells.forEach((v, i) => img.data.set(v ? [23, 195, 140, 110] : [0, 0, 0, 0], i * 4))
      maskCanvas.getContext('2d')!.putImageData(img, 0, 0)
    })
    const inMask = (x: number, y: number) => {
      if (!mask || performance.now() - mask.at > 500) return false
      const cx = Math.floor((x / w) * mask.w), cy = Math.floor((y / h) * mask.h)
      return cx >= 0 && cy >= 0 && cx < mask.w && cy < mask.h && mask.cells[cy * mask.w + cx] > 127
    }

    const menu = (title: string, body: string) =>
      dialog(root, {
        title,
        body,
        actions: LEVELS.map((l, i) => ({
          label: l.name,
          color: [C.mint, C.cobalt, C.tomato][i],
          onTap: () => {
            level = l
            score = 0
            lives = 3
            left = ROUND_S
            items = []
            playing = true
          },
        })),
      })
    menu('Catch', 'Catch the <b class="good">stars</b> with your hands or body. Avoid the <b class="bad">bombs</b>!')

    const stop = loop((dt, now) => {
      const catchers = [...hands.values(), ...(mouse ? [mouse] : [])]
      if (playing) {
        left -= dt
        spawn -= dt
        if (spawn <= 0) {
          spawn = level.every * (0.6 + Math.random() * 0.8)
          const bad = Math.random() < level.bad
          items.push({
            x: 200 + Math.random() * (w - 400),
            y: -ITEM_R,
            vy: level.speed * (0.8 + Math.random() * 0.4),
            bad,
            color: bad ? C.tomato : GOOD[Math.floor(Math.random() * GOOD.length)],
            spin: Math.random() * 6,
          })
        }
        for (const it of items) it.y += it.vy * dt
        items = items.filter((it) => {
          const caught = inMask(it.x, it.y) || catchers.some((c) => Math.hypot(c.x - it.x, c.y - it.y) < CATCH_R + ITEM_R)
          if (caught) {
            const [wx, wy] = toWindow(it.x, it.y)
            burst(wx, wy, it.color, it.bad ? 20 : 12)
            if (it.bad) lives--
            else score++
          }
          return !caught && it.y < h + ITEM_R
        })
        if (left <= 0 || lives <= 0) {
          playing = false
          items = []
          menu(lives <= 0 ? 'Boom!' : 'Time!', `You caught <b>${score}</b> stars on ${level.name}. Again?`)
        }
      }
      hud.innerHTML = `<span class="pill">★ ${score}</span><span class="pill">${'♥'.repeat(Math.max(lives, 0)) || '–'}</span><span class="pill">${clock(Math.max(left, 0))}</span>`

      ctx.fillStyle = C.paper
      ctx.fillRect(0, 0, w, h)
      if (mask && now - mask.at < 500) ctx.drawImage(maskCanvas, 0, 0, w, h)
      ctx.lineWidth = 8
      for (const c of catchers) {
        ctx.strokeStyle = C.mint
        ctx.setLineDash([18, 14])
        ctx.beginPath()
        ctx.arc(c.x, c.y, CATCH_R, 0, Math.PI * 2)
        ctx.stroke()
        ctx.setLineDash([])
      }
      for (const it of items) (it.bad ? drawBomb : drawStar)(ctx, it, now / 1000)
    })
    return () => {
      stop()
      offMask()
      send({ t: 'cmd', name: 'subscribe_mask', value: false })
    }
  },
}

function drawStar(ctx: CanvasRenderingContext2D, it: Item, t: number) {
  ctx.beginPath()
  for (let i = 0; i < 10; i++) {
    const a = it.spin + t * 1.5 + (i * Math.PI) / 5, r = i % 2 ? ITEM_R * 0.48 : ITEM_R
    ctx.lineTo(it.x + Math.cos(a) * r, it.y + Math.sin(a) * r)
  }
  ctx.closePath()
  ctx.fillStyle = it.color
  ctx.fill()
  ctx.lineWidth = 6
  ctx.strokeStyle = darker(it.color)
  ctx.stroke()
}

function drawBomb(ctx: CanvasRenderingContext2D, it: Item, t: number) {
  ctx.lineWidth = 6
  ctx.strokeStyle = darker(it.color)
  ctx.fillStyle = it.color
  ctx.beginPath() // spiky ball
  for (let i = 0; i < 24; i++) {
    const a = it.spin + t + (i * Math.PI) / 12, r = i % 2 ? ITEM_R * 0.78 : ITEM_R
    ctx.lineTo(it.x + Math.cos(a) * r, it.y + Math.sin(a) * r)
  }
  ctx.closePath()
  ctx.fill()
  ctx.stroke()
  ctx.lineWidth = 9 // white X
  ctx.strokeStyle = C.white
  ctx.beginPath()
  const d = ITEM_R * 0.32
  ctx.moveTo(it.x - d, it.y - d)
  ctx.lineTo(it.x + d, it.y + d)
  ctx.moveTo(it.x + d, it.y - d)
  ctx.lineTo(it.x - d, it.y + d)
  ctx.stroke()
}
