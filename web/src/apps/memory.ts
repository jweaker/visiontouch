// Memory: find the matching pairs on a 4x3 grid of big cards.
import { C, burst, clock, dialog, shuffle, type App } from '../ui'

// Six bold shapes, each with its own colour, so pairs are easy to tell apart from far away.
const SHAPES = [
  `<circle cx="32" cy="32" r="22" fill="${C.cobalt}"/>`,
  `<rect x="11" y="11" width="42" height="42" rx="6" fill="${C.tomato}"/>`,
  `<path d="M32 8 58 54H6z" fill="${C.sun}"/>`,
  `<path d="M32 6l7 17 18 1-14 12 5 18-16-10-16 10 5-18L7 24l18-1z" fill="${C.mint}"/>`,
  `<path d="M32 56S6 40 6 22a13 13 0 0 1 26-3 13 13 0 0 1 26 3c0 18-26 34-26 34z" fill="${C.pink}"/>`,
  `<path d="M32 6l23 13v26L32 58 9 45V19z" fill="${C.sky}"/>`,
]

export const memory: App = {
  id: 'memory',
  title: 'Memory',
  blurb: 'Find the six pairs.',
  color: C.sky,
  icon: '<svg viewBox="0 0 64 64"><rect x="8" y="14" width="26" height="36" rx="4"/><rect x="30" y="10" width="26" height="36" rx="4"/></svg>',

  mount(root) {
    root.innerHTML = `<div class="memory"><div class="hud"></div><div class="cards"></div></div>`
    const grid = root.querySelector<HTMLElement>('.cards')!
    const hud = root.querySelector<HTMLElement>('.hud')!
    let open: HTMLElement[] = [], moves = 0, found = 0, started = 0, timer = 0

    const status = () =>
      (hud.innerHTML = `<span class="pill">Moves ${moves}</span><span class="pill">Pairs ${found} / 6</span><span class="pill">${clock(started ? (performance.now() - started) / 1000 : 0)}</span>`)

    function deal() {
      open = []
      moves = found = started = 0
      grid.innerHTML = shuffle([...SHAPES.keys(), ...SHAPES.keys()])
        .map((k) => `<button class="card tap" data-k="${k}"><span class="back"></span><svg class="face" viewBox="0 0 64 64">${SHAPES[k]}</svg></button>`)
        .join('')
      status()
    }

    grid.addEventListener('click', (e) => {
      const card = (e.target as Element).closest<HTMLElement>('.card')
      if (!card || card.classList.contains('open') || open.length === 2) return
      started ||= performance.now()
      card.classList.add('open')
      open.push(card)
      if (open.length < 2) return
      moves++
      const [a, b] = open
      if (a.dataset.k === b.dataset.k) {
        found++
        for (const c of open) c.classList.add('matched')
        burst(e.clientX, e.clientY, C.mint, 18)
        open = []
        if (found === 6)
          dialog(root, {
            title: 'All pairs found!',
            body: `${moves} moves in ${clock((performance.now() - started) / 1000)}.`,
            actions: [{ label: 'Play again', onTap: deal }],
          })
      } else {
        setTimeout(() => {
          for (const c of open) c.classList.remove('open')
          open = []
        }, 1000)
      }
      status()
    })
    deal()
    timer = window.setInterval(() => found < 6 && status(), 1000)
    return () => clearInterval(timer)
  },
}
