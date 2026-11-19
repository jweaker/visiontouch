// Small helpers shared by the apps.

/** Every app is one of these. mount() builds the app inside `root` and returns its cleanup. */
export interface App {
  id: string
  title: string
  blurb: string
  color: string // CSS colour of its launcher tile
  icon: string // inline SVG
  mount(root: HTMLElement): () => void
}

/** The palette, also used by canvas apps. Saturated so it survives a washed-out projector. */
export const C = {
  paper: '#FFF6E6',
  ink: '#17153B',
  cobalt: '#2F5BFF',
  tomato: '#FF5A36',
  sun: '#FFC93C',
  mint: '#17C38C',
  pink: '#FF4FA3',
  sky: '#38C6FF',
  white: '#FFFFFF',
}

/** Build an element from an HTML string. */
export function html<T extends HTMLElement = HTMLElement>(markup: string): T {
  const t = document.createElement('template')
  t.innerHTML = markup.trim()
  return t.content.firstElementChild as T
}

/** Size a canvas to its CSS box at device resolution; drawing then uses CSS pixels. */
export function fitCanvas(canvas: HTMLCanvasElement) {
  const dpr = devicePixelRatio || 1
  const w = canvas.clientWidth, h = canvas.clientHeight
  canvas.width = Math.round(w * dpr)
  canvas.height = Math.round(h * dpr)
  const ctx = canvas.getContext('2d')!
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  return { ctx, w, h }
}

/** requestAnimationFrame loop with dt in seconds. Returns stop(). */
export function loop(fn: (dt: number, now: number) => void) {
  let last = performance.now(), id = 0
  const tick = (now: number) => {
    fn(Math.min((now - last) / 1000, 0.1), now)
    last = now
    id = requestAnimationFrame(tick)
  }
  id = requestAnimationFrame(tick)
  return () => cancelAnimationFrame(id)
}

export const shuffle = <T>(a: T[]) => {
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[a[i], a[j]] = [a[j], a[i]]
  }
  return a
}

/** A short burst of confetti dots at window position (x, y). Small and local, so the detector doesn't mind. */
export function burst(x: number, y: number, color: string, n = 12) {
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2 + Math.random() * 0.4, d = 70 + Math.random() * 70
    const dot = html(`<i class="spark" style="left:${x}px;top:${y}px;background:${color}"></i>`)
    dot.style.setProperty('--dx', `${Math.cos(a) * d}px`)
    dot.style.setProperty('--dy', `${Math.sin(a) * d}px`)
    dot.addEventListener('animationend', () => dot.remove())
    document.body.append(dot)
  }
}

/**
 * A centred card over an app (start screens, results). Each action is a big button.
 * Returns a function that closes it.
 */
export function dialog(
  root: HTMLElement,
  opts: { title: string; body?: string; actions: { label: string; color?: string; onTap: () => void }[] },
) {
  const el = html(`
    <div class="scrim"><div class="dialog">
      <h2>${opts.title}</h2>
      ${opts.body ? `<div class="dialog-body">${opts.body}</div>` : ''}
      <div class="dialog-actions"></div>
    </div></div>`)
  for (const a of opts.actions) {
    const b = html(`<button class="btn big" style="--c:${a.color ?? C.cobalt}">${a.label}</button>`)
    b.addEventListener('click', () => {
      el.remove()
      a.onTap()
    })
    el.querySelector('.dialog-actions')!.append(b)
  }
  root.append(el)
  return () => el.remove()
}

/** "1:05" */
export const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`
