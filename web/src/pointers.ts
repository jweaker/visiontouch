// Pointer shim: turns the engine's `pointers` messages into ordinary DOM PointerEvents,
// so every app is written once against pointer events and works with a mouse too.
// It also draws a cursor ring per hand, because seeing the system's guess makes lag tolerable.

import { engine, on } from './engine'
import { toWindow } from './warp'

export type Pose = 'point' | 'pinch' | 'palm' | 'fist'

/** A tracked hand. x, y are content-box pixels. */
export interface Hand {
  id: number
  pointerId: number
  x: number
  y: number
  down: boolean
  pose: Pose
}

interface EnginePointer {
  id: number
  x: number
  y: number
  down: boolean
  pose?: Pose
}

/** Current hands, keyed by the pointerId their DOM events carry. */
export const hands = new Map<number, Hand>()

/** Pose of the hand behind a pointer event (undefined for mouse). */
export const poseOf = (pointerId: number) => hands.get(pointerId)?.pose

export const onGesture = (fn: (name: string) => void) => on('gesture', (m) => fn(m.name))

// Hand ids become pointerIds 1000+ so they never collide with the mouse (pointerId 1).
const POINTER_ID_BASE = 1000
// A down→up counts as a click if it ends on the same element or moved less than this
// fraction of the window width (hands jitter by 1-2 cm), within CLICK_MS.
const CLICK_DIST = 0.04
const CLICK_MS = 1500
// Dwell click, mirrored from the engine (visiontouch/track.py): a hand that stays within
// DWELL_RADIUS (normalised content units) for DWELL_MS gets one click from the engine. We only
// draw the progress; the engine makes the click.
const DWELL_RADIUS = 0.04
const DWELL_MS = 800

interface Track {
  hand: Hand
  wx: number // window pixels
  wy: number
  target: Element | null // element that got pointerdown: touch pointers are implicitly captured
  downAt: number
  downX: number
  downY: number
  ring: HTMLElement
  anchorX: number // dwell anchor, normalised
  anchorY: number
  anchorAt: number
  armed: boolean // one dwell click per anchor, like the engine
}
const tracks = new Map<number, Track>()

function fire(type: string, target: Element, t: Track, primary: boolean) {
  const down = type === 'pointerdown' || (type === 'pointermove' && t.hand.down)
  target.dispatchEvent(
    new PointerEvent(type, {
      bubbles: true,
      cancelable: true,
      composed: true,
      pointerId: t.hand.pointerId,
      pointerType: 'touch',
      isPrimary: primary,
      clientX: t.wx,
      clientY: t.wy,
      screenX: t.wx,
      screenY: t.wy,
      button: type === 'pointermove' ? -1 : 0,
      buttons: down ? 1 : 0,
      pressure: down ? 0.5 : 0,
      width: 40,
      height: 40,
    }),
  )
}

let ringLayer: HTMLElement | null = null
function makeRing() {
  if (!ringLayer?.isConnected) {
    ringLayer = document.createElement('div')
    ringLayer.className = 'rings'
    document.body.append(ringLayer)
  }
  const ring = document.createElement('div')
  ring.className = 'ring'
  ringLayer.append(ring)
  return ring
}

/** Handle one `pointers` message: list of hands with normalised content-box positions. */
export function handlePointers(list: EnginePointer[], now = performance.now()) {
  const W = innerWidth, H = innerHeight
  const dispatch = engine.state?.mode !== 'desktop' // in desktop mode the engine drives the OS mouse
  const seen = new Set<number>()

  list.forEach((p, i) => {
    seen.add(p.id)
    let t = tracks.get(p.id)
    if (!t) {
      const hand: Hand = { id: p.id, pointerId: POINTER_ID_BASE + p.id, x: 0, y: 0, down: false, pose: 'point' }
      t = { hand, wx: 0, wy: 0, target: null, downAt: 0, downX: 0, downY: 0, ring: makeRing(), anchorX: p.x, anchorY: p.y, anchorAt: now, armed: true }
      tracks.set(p.id, t)
      hands.set(hand.pointerId, hand)
    }
    const wasDown = t.hand.down
    Object.assign(t.hand, { x: p.x * W, y: p.y * H, down: p.down, pose: p.pose ?? 'point' })
    ;[t.wx, t.wy] = toWindow(t.hand.x, t.hand.y)
    t.ring.className = `ring ${p.down ? 'down' : ''} ${t.hand.pose}`
    t.ring.style.transform = `translate(${t.wx}px, ${t.wy}px)`
    if (Math.hypot(p.x - t.anchorX, p.y - t.anchorY) > DWELL_RADIUS)
      Object.assign(t, { anchorX: p.x, anchorY: p.y, anchorAt: now, armed: true })
    // (also while down: in the engine's "hold" dwell mode the next hold releases the press)
    let dwell = t.armed ? (now - t.anchorAt) / DWELL_MS : 0
    if (dwell >= 1) {
      t.armed = false // the engine clicks now; the ring empties until the hand moves on
      dwell = 0
    }
    t.ring.style.setProperty('--dwell', dwell.toFixed(3))
    if (!dispatch) return

    const under = document.elementFromPoint(t.wx, t.wy) ?? document.documentElement
    const captured = t.target?.isConnected ? t.target : under
    const primary = i === 0
    if (p.down && !wasDown) {
      Object.assign(t, { target: under, downAt: now, downX: t.wx, downY: t.wy })
      fire('pointerdown', under, t, primary)
    } else if (p.down) {
      fire('pointermove', captured, t, primary)
    } else if (wasDown) {
      fire('pointerup', captured, t, primary)
      const near = Math.hypot(t.wx - t.downX, t.wy - t.downY) < CLICK_DIST * W
      if ((near || captured.contains(under)) && now - t.downAt < CLICK_MS) {
        captured.dispatchEvent(
          new MouseEvent('click', { bubbles: true, cancelable: true, composed: true, clientX: t.wx, clientY: t.wy, detail: 1 }),
        )
      }
      t.target = null
    } else {
      fire('pointermove', under, t, primary) // hover
    }
  })

  // Hands that vanished: cancel an unfinished touch and drop the ring.
  for (const [id, t] of tracks) {
    if (seen.has(id)) continue
    if (t.hand.down && dispatch) fire('pointercancel', t.target?.isConnected ? t.target : document.documentElement, t, false)
    t.ring.remove()
    tracks.delete(id)
    hands.delete(t.hand.pointerId)
  }
}

export function startPointerShim() {
  on('pointers', (m) => handlePointers(m.p ?? []))
  on('connection', () => handlePointers([])) // engine gone: release every hand
}
