// Settings: calibrate, keystone on/off, switch apps/desktop mode, pick the camera, and see the engine's live state.
import { engine, on, send } from '../engine'
import { C, type App } from '../ui'

export const settings: App = {
  id: 'settings',
  title: 'Settings',
  blurb: 'Calibrate, mode, camera.',
  color: C.white,
  icon: '<svg viewBox="0 0 64 64"><path d="M10 18h44M10 32h44M10 46h44"/><circle cx="22" cy="18" r="6"/><circle cx="42" cy="32" r="6"/><circle cx="28" cy="46" r="6"/></svg>',

  mount(root) {
    root.innerHTML = `
      <div class="settings">
        <h1>Settings</h1>
        <section class="panel live"><h2>Engine</h2><p class="engine-msg" hidden></p><dl></dl></section>
        <section class="panel">
          <h2>Calibration</h2>
          <p>Shows a few patterns so the camera can learn where the screen is. Stand clear of the picture.</p>
          <div class="row">
            <button class="btn big" data-cmd="calibrate" style="--c:${C.sun}">Calibrate now</button>
            <button class="switch" role="switch" aria-checked="false" data-keystone><i></i>Keystone</button>
          </div>
          <div class="pair">
            <div>
              <h2>Mode</h2>
              <div class="segmented">
                <button class="btn big" data-mode="apps">Apps</button>
                <button class="btn big" data-mode="desktop">Desktop</button>
              </div>
            </div>
            <div>
              <!-- More: finds fainter hands (weak projector, bright room). Less: fewer false hands. -->
              <h2>Sensitivity</h2>
              <div class="row">
                <button class="btn big" data-sensitivity="-0.25">Less</button>
                <button class="btn big" data-sensitivity="0.25">More</button>
              </div>
            </div>
          </div>
          <h2>Camera</h2>
          <div class="row">
            ${['0', '1', 'android'].map((c) => `<button class="btn big" data-camera="${c}" style="--c:${C.white}">${c === 'android' ? 'Phone (USB)' : c}</button>`).join('')}
            <input class="field" placeholder="0 or URL">
            <button class="btn big" data-camera-field>Use</button>
          </div>
        </section>
      </div>`
    const dl = root.querySelector('dl')!
    const msg = root.querySelector<HTMLElement>('.engine-msg')!
    const keystone = root.querySelector<HTMLElement>('[data-keystone]')!
    const input = root.querySelector('input')!

    function render() {
      const s = engine.state
      const rows: [string, string][] = engine.connected
        ? [
            // Mode and keystone are shown by their own controls; these are the read-only values.
            ['Camera', s?.camera || '—'],
            ['Speed', s ? `${s.fps.toFixed(0)} fps` : '—'],
            ['Delay', s ? `${Math.round(s.latency_ms)} ms` : '—'],
            ['Sensitivity', s?.sensitivity ? `${s.sensitivity.toFixed(2)}×` : '—'],
          ]
        : [['Status', 'Not connected'], ['', 'Start the VisionTouch engine; this page connects by itself.']]
      dl.innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')
      // The engine reports calibration results and failures here.
      msg.textContent = (engine.connected && s?.message) || ''
      msg.hidden = !msg.textContent
      msg.classList.toggle('bad', /fail|cannot|could not|not connected/i.test(msg.textContent))
      keystone.setAttribute('aria-checked', String(!!s?.keystone))
      root.querySelectorAll<HTMLButtonElement>('[data-cmd],[data-mode],[data-camera],[data-camera-field],[data-keystone],[data-sensitivity]').forEach((b) => {
        b.disabled = !engine.connected
        b.classList.toggle('on', b.dataset.mode === s?.mode)
      })
    }
    render()
    const offState = on('state', render)
    const offConn = on('connection', render)

    root.addEventListener('click', (e) => {
      const b = (e.target as Element).closest<HTMLElement>('button')
      if (!b) return
      if (b.dataset.cmd) send({ t: 'cmd', name: b.dataset.cmd })
      if ('keystone' in b.dataset) send({ t: 'cmd', name: 'keystone', value: !engine.state?.keystone })
      if (b.dataset.sensitivity) send({ t: 'cmd', name: 'sensitivity', value: (engine.state?.sensitivity ?? 1) + +b.dataset.sensitivity })
      if (b.dataset.mode) send({ t: 'cmd', name: 'mode', value: b.dataset.mode })
      if (b.dataset.camera) send({ t: 'cmd', name: 'camera', value: b.dataset.camera })
      if ('cameraField' in b.dataset && input.value.trim()) send({ t: 'cmd', name: 'camera', value: input.value.trim() })
    })
    return () => {
      offState()
      offConn()
    }
  },
}
