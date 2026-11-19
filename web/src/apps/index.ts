// The app list and the launcher (home screen).
import { engine, on } from '../engine'
import { C, type App } from '../ui'
import { board } from './board'
import { balloons } from './balloons'
import { catchGame } from './catch'
import { slides } from './slides'
import { quiz } from './quiz'
import { memory } from './memory'
import { accuracy } from './accuracy'
import { pipeline } from './pipeline'
import { settings } from './settings'

export const apps: App[] = [board, balloons, catchGame, slides, quiz, memory, accuracy, pipeline, settings]

// Light colours need a dark icon on the tile's icon chip.
const fg = (color: string) => ([C.sun, C.white, C.sky].includes(color) ? C.ink : C.white)

function statusText() {
  const s = engine.state
  if (!engine.connected) return { cls: 'off', text: 'Engine offline · mouse works' }
  if (!s) return { cls: 'warn', text: 'Engine connected' }
  const parts = [s.calibrated ? 'Calibrated' : 'Not calibrated', s.camera, `${Math.round(s.fps)} fps`, `${Math.round(s.latency_ms)} ms`]
  return { cls: s.calibrated ? 'ok' : 'warn', text: parts.filter(Boolean).join(' · ') }
}

export const launcher: App = {
  id: 'home',
  title: 'Home',
  blurb: '',
  color: C.paper,
  icon: '',

  mount(root) {
    root.innerHTML = `
      <div class="launcher">
        <header>
          <div class="brand">
            <svg class="logo" viewBox="0 0 64 64"><rect x="3" y="3" width="58" height="58" rx="16" fill="${C.cobalt}"/><circle cx="32" cy="32" r="15" fill="none" stroke="#fff" stroke-width="6"/><circle cx="32" cy="32" r="5" fill="${C.sun}"/></svg>
            <div><h1>VisionTouch</h1><p class="tagline">Smart Projector Board</p></div>
          </div>
          <button class="chip tap" data-go="settings"><i></i><span></span></button>
        </header>
        <nav class="tiles">
          ${apps
            .map(
              (a, i) => `
            <button class="tile ${i === 0 ? 'hero' : ''}" data-go="${a.id}" style="--c:${a.color};--fg:${fg(a.color)}">
              <span class="icon">${a.icon}</span>
              <span><h3>${a.title}</h3><p>${a.blurb}</p></span>
            </button>`,
            )
            .join('')}
        </nav>
        <footer>Point at a tile, then pinch or touch the wall. To come back, hold the house button in the top-right corner for one second.</footer>
      </div>`
    root.querySelectorAll<HTMLElement>('[data-go]').forEach((b) => b.addEventListener('click', () => (location.hash = b.dataset.go!)))

    const chip = root.querySelector<HTMLElement>('.chip')!
    const render = () => {
      const s = statusText()
      chip.className = `chip tap ${s.cls}`
      chip.querySelector('span')!.textContent = s.text
    }
    render()
    const offs = [on('state', render), on('connection', render)]
    return () => offs.forEach((off) => off())
  },
}
