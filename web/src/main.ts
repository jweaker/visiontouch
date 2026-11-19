// The shell: content box + keystone warp, calibration pattern overlay, app switching,
// the hold-to-go-home button and touch feedback. Apps live in src/apps/.
import '@fontsource-variable/bricolage-grotesque/wght.css'
import '@fontsource/atkinson-hyperlegible/latin-400.css'
import '@fontsource/atkinson-hyperlegible/latin-700.css'
import './style.css'
import { connect, emit, engine, on, send } from './engine'
import { setWarp, toMatrix3d } from './warp'
import { startPointerShim } from './pointers'
import { apps, launcher } from './apps'
import { burst, html } from './ui'

// The content box: everything the user sees, warped as one piece for keystone correction.
const stage = html(`<div id="stage"><div id="view"></div>
  <button id="home" aria-label="Hold for home">
    <svg viewBox="0 0 100 100"><circle class="track" cx="50" cy="50" r="42"/><circle class="fill" cx="50" cy="50" r="42" pathLength="100"/></svg>
    <svg class="house" viewBox="0 0 64 64"><path d="M10 30 32 11l22 19M17 25v28h30V25"/></svg>
    <b>Hold for home</b>
  </button></div>`)
document.body.append(stage)
const view = stage.querySelector<HTMLElement>('#view')!
const home = stage.querySelector<HTMLElement>('#home')!

// Desktop mode: the engine shrinks this window to a small strip and drives the OS mouse.
// The strip shows one button back, and the keystone warp does not apply to it.
const back = html(`<button id="back">Back to VisionTouch</button>`)
back.addEventListener('click', () => send({ t: 'cmd', name: 'mode', value: 'apps' }))
document.body.append(back)
let warp: number[] | null = null
const desktop = () => engine.state?.mode === 'desktop'
function applyWarp() {
  const m = desktop() ? null : warp
  const H = setWarp(m)
  stage.style.transform = m ? toMatrix3d(H) : '' // outside the content box the body stays black
}
on('warp', (m) => {
  warp = m.m
  applyWarp()
})

// Engine status: desktop mode, and a big toast while calibration is running.
const toast = html(`<div id="toast" hidden></div>`)
stage.append(toast)
function onState() {
  document.body.classList.toggle('desktop', desktop())
  applyWarp()
  const msg = engine.state?.message ?? ''
  toast.hidden = !msg.startsWith('Calibrating')
  toast.textContent = msg
}
on('state', onState)
on('connection', onState)

// Calibration patterns: full window, unwarped, above everything, nothing else visible.
// The image is stretched to the window with pixelated scaling, so a pattern rendered at
// window size in device pixels lands 1:1 on device pixels.
const pattern = html<HTMLImageElement>(`<img id="pattern" alt="">`)
document.body.append(pattern)
let patternId: number | null = null
on('pattern', async (m) => {
  patternId = m.id
  if (!m.url) {
    document.body.classList.remove('pattern-on')
    pattern.removeAttribute('src')
    return
  }
  pattern.src = m.url
  try {
    await pattern.decode()
  } catch {
    return // broken image: don't claim it was shown
  }
  if (patternId !== m.id) return // a newer pattern arrived meanwhile
  document.body.classList.add('pattern-on')
  // Two frames: the first paints, the second guarantees the paint reached the screen.
  requestAnimationFrame(() => requestAnimationFrame(() => {
    if (patternId === m.id) send({ t: 'pattern_shown', id: m.id })
  }))
})

// App switching via the URL hash (#board), so a page reload keeps the current app.
let unmount = () => {}
function route() {
  unmount()
  view.replaceChildren()
  const app = apps.find((a) => `#${a.id}` === location.hash) ?? launcher
  view.dataset.app = app.id
  home.hidden = app === launcher
  unmount = app.mount(view)
}
addEventListener('hashchange', route)
const goHome = () => (location.hash = '')
addEventListener('keydown', (e) => e.key === 'Escape' && goHome())

// Home needs a one-second hold: easy on purpose, hard by accident. The ring fills meanwhile.
let holdTimer = 0
const release = () => {
  clearTimeout(holdTimer)
  home.classList.remove('holding')
}
home.addEventListener('pointerdown', () => {
  home.classList.add('holding')
  holdTimer = window.setTimeout(() => {
    release()
    goHome()
  }, 1000)
})
for (const ev of ['pointerup', 'pointercancel', 'pointerleave']) home.addEventListener(ev, release)

// Touch feedback everywhere: a ripple on every press, a pressed state on buttons, and a
// highlight on whatever a hovering hand points at (hands have no CSS :hover).
const target = (e: Event) => (e.target as Element).closest?.('button, .tap, label.btn')
document.addEventListener('pointerdown', (e) => {
  const ripple = html(`<i class="ripple" style="left:${e.clientX}px;top:${e.clientY}px"></i>`)
  ripple.addEventListener('animationend', () => ripple.remove())
  document.body.append(ripple)
  const b = target(e)
  if (b) {
    b.classList.add('pressed')
    if (b.classList.contains('tile')) burst(e.clientX, e.clientY, getComputedStyle(b).getPropertyValue('--c'), 10)
  }
}, true)
const unpress = () => document.querySelectorAll('.pressed').forEach((b) => b.classList.remove('pressed'))
document.addEventListener('pointerup', unpress, true)
document.addEventListener('pointercancel', unpress, true)
const hot = new Map<number, Element>()
document.addEventListener('pointermove', (e) => {
  if (e.pointerType !== 'touch') return
  const b = target(e)
  if (hot.get(e.pointerId) === b) return
  hot.get(e.pointerId)?.classList.remove('hot')
  hot.delete(e.pointerId)
  if (b) {
    b.classList.add('hot')
    hot.set(e.pointerId, b)
  }
}, true)
on('pointers', (m) => {
  // drop highlights of hands that vanished
  const live = new Set((m.p as { id: number }[]).map((p) => 1000 + p.id))
  for (const [id, b] of hot) {
    if (live.has(id)) continue
    b.classList.remove('hot')
    hot.delete(id)
  }
})

startPointerShim()
connect()
route()

// For tests and debugging from the console: feed a message as if the engine sent it.
;(window as any).visiontouch = { emit }
