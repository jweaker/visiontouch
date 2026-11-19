// Freehand ink shared by Board and Slides.
// Hand input is jittery and arrives ~30 times a second, so each new sample is first pulled
// part-way towards the previous one (exponential smoothing), then the stroke is drawn as
// quadratic curves through the midpoints of consecutive samples, which hides the corners.

export interface Stroke {
  color: string
  size: number
  points: { x: number; y: number }[]
}

const SMOOTHING = 0.45 // 0 = raw input, closer to 1 = smoother but laggier

/** Add a sample to a stroke and draw the new piece. */
export function extend(ctx: CanvasRenderingContext2D, s: Stroke, x: number, y: number) {
  const p = s.points.at(-1)
  if (p) {
    x = p.x + (x - p.x) * (1 - SMOOTHING)
    y = p.y + (y - p.y) * (1 - SMOOTHING)
  }
  s.points.push({ x, y })
  drawTail(ctx, s, s.points.length - 1)
}

// Draw the piece of the stroke that ends at point i.
function drawTail(ctx: CanvasRenderingContext2D, s: Stroke, i: number) {
  const pts = s.points
  ctx.strokeStyle = ctx.fillStyle = s.color
  ctx.lineWidth = s.size
  ctx.lineCap = ctx.lineJoin = 'round'
  if (i === 0) {
    ctx.beginPath()
    ctx.arc(pts[0].x, pts[0].y, s.size / 2, 0, Math.PI * 2)
    ctx.fill()
    return
  }
  const a = pts[i - 2] ?? pts[i - 1], b = pts[i - 1], c = pts[i]
  ctx.beginPath()
  ctx.moveTo((a.x + b.x) / 2, (a.y + b.y) / 2)
  ctx.quadraticCurveTo(b.x, b.y, (b.x + c.x) / 2, (b.y + c.y) / 2)
  ctx.stroke()
}

/** Draw whole strokes (after undo, page change, ...). */
export function drawAll(ctx: CanvasRenderingContext2D, strokes: Stroke[]) {
  for (const s of strokes) for (let i = 0; i < s.points.length; i++) drawTail(ctx, s, i)
}
