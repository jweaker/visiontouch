// Board: freehand drawing. Pointer down draws; an open palm (pose "palm") wipes with a big eraser.
import { contentPoint } from '../warp'
import { poseOf } from '../pointers'
import { drawAll, extend, type Stroke } from '../ink'
import { C, fitCanvas, type App } from '../ui'

const COLORS = [C.ink, C.cobalt, C.tomato, C.mint, C.pink]
const SIZES = [8, 18, 34]
const ERASER = 60
const PALM_ERASER = 160

export const board: App = {
  id: 'board',
  title: 'Board',
  blurb: 'Draw with your finger. Open your palm to erase.',
  color: C.cobalt,
  icon: '<svg viewBox="0 0 64 64"><path d="M8 46c8-16 16-24 22-16s10 10 26-14"/><circle cx="12" cy="54" r="3"/></svg>',

  mount(root) {
    root.innerHTML = `
      <div class="board">
        <canvas class="full"></canvas>
        <div class="toolbar">
          ${COLORS.map((c, i) => `<button class="tool swatch" data-color="${i}" style="--c:${c}" aria-label="Colour"></button>`).join('')}
          <button class="tool" data-act="eraser">Eraser</button>
          ${SIZES.map((s, i) => `<button class="tool size" data-size="${i}" aria-label="Pen size"><i style="width:${s + 6}px;height:${s + 6}px"></i></button>`).join('')}
          <button class="tool" data-act="undo">Undo</button>
          <button class="tool" data-act="clear">Clear</button>
          <button class="tool" data-act="save">Save</button>
        </div>
      </div>`
    const canvas = root.querySelector('canvas')!
    const { ctx, w, h } = fitCanvas(canvas)
    const strokes: Stroke[] = []
    const live = new Map<number, Stroke>() // pointerId → stroke in progress (several hands at once)
    let color = COLORS[0], size = SIZES[1], erasing = false

    const redraw = () => {
      ctx.fillStyle = C.white
      ctx.fillRect(0, 0, w, h)
      drawAll(ctx, strokes)
    }
    redraw()

    // Highlight the chosen tool.
    const sync = () =>
      root.querySelectorAll<HTMLElement>('.tool').forEach((b) => {
        const on =
          (b.dataset.color && !erasing && COLORS[+b.dataset.color] === color) ||
          (b.dataset.size && SIZES[+b.dataset.size] === size && !erasing) ||
          (b.dataset.act === 'eraser' && erasing)
        b.classList.toggle('on', !!on)
      })
    sync()

    root.querySelector('.toolbar')!.addEventListener('click', (e) => {
      const b = (e.target as Element).closest<HTMLElement>('.tool')
      if (!b) return
      if (b.dataset.color) {
        color = COLORS[+b.dataset.color]
        erasing = false
      }
      if (b.dataset.size) {
        size = SIZES[+b.dataset.size]
        erasing = false
      }
      const act = b.dataset.act
      if (act === 'eraser') erasing = !erasing
      if (act === 'undo') strokes.pop()
      if (act === 'clear') strokes.length = 0
      if (act === 'undo' || act === 'clear') redraw()
      if (act === 'save') {
        const a = document.createElement('a')
        a.download = `visiontouch-board-${Date.now()}.png`
        a.href = canvas.toDataURL('image/png')
        a.click()
      }
      sync()
    })

    const start = (e: PointerEvent, stroke: Stroke) => {
      live.set(e.pointerId, stroke)
      strokes.push(stroke)
      const p = contentPoint(e)
      extend(ctx, stroke, p.x, p.y)
    }
    canvas.addEventListener('pointerdown', (e) => {
      const palm = poseOf(e.pointerId) === 'palm'
      start(e, { color: erasing || palm ? C.white : color, size: palm ? PALM_ERASER : erasing ? ERASER : size, points: [] })
    })
    canvas.addEventListener('pointermove', (e) => {
      const palm = poseOf(e.pointerId) === 'palm'
      const s = live.get(e.pointerId)
      // An open palm erases even without "down" (the promised gesture) until the palm closes.
      if (!s && palm) return start(e, { color: C.white, size: PALM_ERASER, points: [] })
      // Nothing pressed any more (palm closed, or a mouse released outside the canvas): stroke over.
      if (s && !palm && e.buttons === 0) return live.delete(e.pointerId)
      if (s) {
        const p = contentPoint(e)
        extend(ctx, s, p.x, p.y)
      }
    })
    const end = (e: PointerEvent) => live.delete(e.pointerId)
    canvas.addEventListener('pointerup', end)
    canvas.addEventListener('pointercancel', end)
    return () => {}
  },
}
