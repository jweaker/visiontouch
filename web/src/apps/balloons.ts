// Balloons: pop rising balloons by touching them. Any number of hands at once.
import { contentPoint, toWindow } from '../warp'
import { C, burst, clock, dialog, fitCanvas, html, loop, type App } from '../ui'

const LEVELS = [
  { name: 'Easy', speed: 110, every: 0.9, r: 95 },
  { name: 'Normal', speed: 170, every: 0.6, r: 80 },
  { name: 'Hard', speed: 250, every: 0.42, r: 66 },
]
const ROUND_S = 45
const COLORS = [C.tomato, C.cobalt, C.sun, C.mint, C.pink, C.sky]

interface Balloon { x: number; y: number; r: number; vy: number; color: string; phase: number }

export const balloons: App = {
  id: 'balloons',
  title: 'Balloons',
  blurb: 'Pop as many as you can.',
  color: C.tomato,
  icon: '<svg viewBox="0 0 64 64"><ellipse cx="32" cy="24" rx="16" ry="19"/><path d="M32 43c-4 6 4 9 0 17"/></svg>',

  mount(root) {
    root.append(html('<canvas class="full"></canvas>'), html('<div class="hud"></div>'))
    const canvas = root.querySelector('canvas')!
    const hud = root.querySelector<HTMLElement>('.hud')!
    const { ctx, w, h } = fitCanvas(canvas)
    let list: Balloon[] = []
    let level = LEVELS[0], score = 0, left = 0, spawn = 0, playing = false

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
            left = ROUND_S
            list = []
            playing = true
          },
        })),
      })
    menu('Balloons', `Touch a balloon to pop it. You have ${ROUND_S} seconds.`)

    const pop = (e: PointerEvent) => {
      if (!playing) return
      const p = contentPoint(e)
      for (const b of list) {
        if (Math.hypot(p.x - b.x, p.y - b.y) > b.r * 1.15) continue // a little grace for jittery hands
        list = list.filter((x) => x !== b)
        score++
        const [wx, wy] = toWindow(b.x, b.y)
        burst(wx, wy, b.color, 16)
        return
      }
    }
    canvas.addEventListener('pointerdown', pop)
    canvas.addEventListener('pointermove', (e) => e.buttons && pop(e)) // dragging a pressed finger pops too

    const stop = loop((dt, now) => {
      if (playing) {
        left -= dt
        spawn -= dt
        if (spawn <= 0) {
          spawn = level.every * (0.6 + Math.random() * 0.8)
          const r = level.r * (0.85 + Math.random() * 0.3)
          list.push({
            x: r + 220 + Math.random() * (w - 2 * r - 440), // keep clear of the HUD and home corners
            y: h + r,
            r,
            vy: level.speed * (0.8 + Math.random() * 0.4),
            color: COLORS[Math.floor(Math.random() * COLORS.length)],
            phase: Math.random() * 6,
          })
        }
        for (const b of list) b.y -= b.vy * dt
        list = list.filter((b) => b.y > -b.r * 2)
        if (left <= 0) {
          playing = false
          list = []
          menu(`${score} popped!`, `Level ${level.name}. Play again?`)
        }
      }
      hud.innerHTML = `<span class="pill">★ ${score}</span><span class="pill">${clock(Math.max(left, 0))}</span>`

      ctx.fillStyle = C.paper
      ctx.fillRect(0, 0, w, h)
      for (const b of list) drawBalloon(ctx, b, b.x + Math.sin(now / 600 + b.phase) * 12)
    })
    return stop
  },
}

function drawBalloon(ctx: CanvasRenderingContext2D, b: Balloon, x: number) {
  ctx.lineWidth = 6
  ctx.strokeStyle = C.ink
  ctx.beginPath() // string
  ctx.moveTo(x, b.y + b.r * 1.15)
  ctx.quadraticCurveTo(x - 14, b.y + b.r * 1.5, x, b.y + b.r * 1.9)
  ctx.stroke()
  ctx.fillStyle = b.color
  ctx.beginPath()
  ctx.ellipse(x, b.y, b.r * 0.88, b.r * 1.1, 0, 0, Math.PI * 2)
  ctx.fill()
  ctx.stroke()
  ctx.beginPath() // knot
  ctx.moveTo(x - 10, b.y + b.r * 1.2)
  ctx.lineTo(x + 10, b.y + b.r * 1.2)
  ctx.lineTo(x, b.y + b.r * 1.08)
  ctx.closePath()
  ctx.fill()
  ctx.stroke()
  ctx.fillStyle = 'rgba(255,255,255,.75)' // shine
  ctx.beginPath()
  ctx.ellipse(x - b.r * 0.35, b.y - b.r * 0.45, b.r * 0.16, b.r * 0.28, -0.5, 0, Math.PI * 2)
  ctx.fill()
}
