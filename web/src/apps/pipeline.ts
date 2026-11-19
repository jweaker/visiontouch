// Pipeline view: every stage of the image-processing pipeline, live, with a plain caption.
import { engine, on } from '../engine'
import { C, type App } from '../ui'

const STAGES: [id: string, title: string, caption: string][] = [
  ['camera', 'Camera frame', 'What the camera sees: wall, picture and your hand.'],
  ['rectified', 'Rectified to screen', 'Warped with the calibration homography to line up with the screen.'],
  ['predicted', 'Predicted image', 'What the camera should see if nothing were in front of the screen.'],
  ['residual', 'Difference', 'Camera minus prediction: anything new, like a hand, lights up.'],
  ['mask', 'Mask', 'The difference after thresholding and clean-up: white = in front.'],
  ['overlay', 'Detected fingertips', 'Where the engine thinks each fingertip is.'],
]

export const pipeline: App = {
  id: 'pipeline',
  title: 'Pipeline',
  blurb: 'Watch each step live.',
  color: C.white,
  icon: '<svg viewBox="0 0 64 64"><rect x="6" y="22" width="14" height="20" rx="3"/><rect x="44" y="22" width="14" height="20" rx="3"/><rect x="25" y="22" width="14" height="20" rx="3"/></svg>',

  mount(root) {
    root.innerHTML = `
      <div class="pipeline">
        <h1>How VisionTouch sees you</h1>
        <div class="stages">
          ${STAGES.map(([id, title, caption], i) => `
            <figure data-stage="${id}">
              <div class="frame"><span class="placeholder">Waiting for the engine…</span></div>
              <figcaption><b>${i + 1}. ${title}</b> ${caption}</figcaption>
            </figure>`).join('')}
        </div>
      </div>`

    // Only ask the engine for streams when it's connected; otherwise show friendly placeholders.
    let alive = true
    async function load() {
      let live: string[] = []
      if (engine.connected) {
        try {
          const body = await (await fetch('/debug/stages')).json()
          live = Array.isArray(body) ? body : (body.stages ?? [])
        } catch {
          // no stage list: keep placeholders
        }
      }
      if (!alive) return
      root.querySelectorAll<HTMLElement>('figure').forEach((fig) => {
        const id = fig.dataset.stage!
        fig.querySelector('.frame')!.innerHTML = live.includes(id)
          ? `<img src="/debug/${id}.mjpg" alt="${id}">`
          : `<span class="placeholder">${engine.connected ? 'This stage is not running' : 'Waiting for the engine…'}</span>`
      })
    }
    load()
    const off = on('connection', load)
    return () => {
      alive = false
      off()
      // Stop the MJPEG streams explicitly; some browsers keep them open otherwise.
      root.querySelectorAll('img').forEach((img) => img.removeAttribute('src'))
    }
  },
}
