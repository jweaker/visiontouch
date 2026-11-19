// Slides: show a PDF, flip pages with the big edge zones, arrow keys or a swipe gesture,
// and draw on each page with a pressed finger. Starts with a built-in sample deck.
import type { PDFDocumentLoadingTask, PDFDocumentProxy, RenderTask } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { onGesture } from '../pointers'
import { contentPoint } from '../warp'
import { drawAll, extend, type Stroke } from '../ink'
import { C, fitCanvas, type App } from '../ui'

const INK = { color: C.tomato, size: 10 }

export const slides: App = {
  id: 'slides',
  title: 'Slides',
  blurb: 'Present any PDF.',
  color: C.sun,
  icon: '<svg viewBox="0 0 64 64"><rect x="8" y="10" width="48" height="32" rx="3"/><path d="M32 42v12M22 56h20M26 20l10 6-10 6z"/></svg>',

  mount(root) {
    root.innerHTML = `
      <div class="slides">
        <div class="slides-bar">
          <label class="btn" style="--c:${C.cobalt}">Open PDF<input type="file" accept="application/pdf,.pdf" hidden></label>
          <button class="btn" data-act="clear" style="--c:${C.white};--fg:${C.ink}">Clear ink</button>
          <span class="slides-name pill"></span>
        </div>
        <div class="slides-page"><canvas class="pdf"></canvas><canvas class="ink"></canvas></div>
        <button class="edge prev" aria-label="Previous page"><svg viewBox="0 0 64 64"><path d="M40 12 20 32l20 20"/></svg></button>
        <button class="edge next" aria-label="Next page"><svg viewBox="0 0 64 64"><path d="M24 12l20 20-20 20"/></svg></button>
        <span class="slides-num pill"></span>
        <div class="drop-hint"><span>Drop a PDF to open it</span></div>
      </div>`
    const $ = <T extends Element>(s: string) => root.querySelector<T>(s)!
    const pageBox = $<HTMLElement>('.slides-page')
    const pdfCanvas = $<HTMLCanvasElement>('.pdf')
    const inkCanvas = $<HTMLCanvasElement>('.ink')
    let doc: PDFDocumentProxy | null = null
    let loading: PDFDocumentLoadingTask | null = null
    let index = 0, rendering: RenderTask | null = null, alive = true
    let inkCtx: CanvasRenderingContext2D | null = null
    const ink = new Map<number, Stroke[]>() // page index → strokes on that page
    const live = new Map<number, Stroke>()

    async function show(i: number) {
      if (!doc) return
      index = Math.max(0, Math.min(doc.numPages - 1, i))
      $('.slides-num').textContent = `${index + 1} / ${doc.numPages}`
      const page = await doc.getPage(index + 1)
      if (!alive) return
      // Fit the page into the free area, keeping its aspect ratio.
      const base = page.getViewport({ scale: 1 })
      const scale = Math.min(pageBox.clientWidth / base.width, pageBox.clientHeight / base.height)
      const vp = page.getViewport({ scale: scale * devicePixelRatio })
      for (const c of [pdfCanvas, inkCanvas]) {
        c.style.width = `${vp.width / devicePixelRatio}px`
        c.style.height = `${vp.height / devicePixelRatio}px`
      }
      rendering?.cancel()
      pdfCanvas.width = vp.width
      pdfCanvas.height = vp.height
      rendering = page.render({ canvas: pdfCanvas, viewport: vp })
      rendering.promise.catch(() => {}) // cancelled by a quicker page turn
      inkCtx = fitCanvas(inkCanvas).ctx
      drawAll(inkCtx, ink.get(index) ?? [])
    }

    async function open(src: { url: string } | { data: ArrayBuffer }, name: string) {
      const pdfjs = await import('pdfjs-dist')
      pdfjs.GlobalWorkerOptions.workerSrc = workerUrl
      loading?.destroy() // free the previous document and its worker
      const task = (loading = pdfjs.getDocument(src))
      try {
        const d = await task.promise
        if (!alive || task !== loading) return
        doc = d
        ink.clear()
        $('.slides-name').textContent = name
        show(0)
      } catch {
        if (task === loading) $('.slides-name').textContent = `Could not open ${name}`
      }
    }
    open({ url: '/sample-deck.pdf' }, 'Sample deck')

    const openFile = (f?: File | null) => f && f.arrayBuffer().then((data) => open({ data }, f.name))
    $<HTMLInputElement>('input').addEventListener('change', (e) => openFile((e.target as HTMLInputElement).files?.[0]))
    root.addEventListener('dragover', (e) => {
      e.preventDefault()
      root.classList.add('dragging')
    })
    root.addEventListener('dragleave', () => root.classList.remove('dragging'))
    root.addEventListener('drop', (e) => {
      e.preventDefault()
      root.classList.remove('dragging')
      openFile(e.dataTransfer?.files[0])
    })

    $('.prev').addEventListener('click', () => show(index - 1))
    $('.next').addEventListener('click', () => show(index + 1))
    $('[data-act=clear]').addEventListener('click', () => {
      ink.delete(index)
      show(index)
    })
    const onKey = (e: KeyboardEvent) => {
      if (['ArrowRight', 'PageDown', ' '].includes(e.key)) show(index + 1)
      if (['ArrowLeft', 'PageUp'].includes(e.key)) show(index - 1)
    }
    addEventListener('keydown', onKey)
    // Swiping left pulls the next page in, like on a phone.
    const offGesture = onGesture((g) => {
      if (g === 'swipe_left') show(index + 1)
      if (g === 'swipe_right') show(index - 1)
    })

    // Annotations, in ink-canvas pixels.
    const local = (e: PointerEvent) => {
      const p = contentPoint(e)
      return { x: p.x - pageBox.offsetLeft - inkCanvas.offsetLeft, y: p.y - pageBox.offsetTop - inkCanvas.offsetTop }
    }
    inkCanvas.addEventListener('pointerdown', (e) => {
      if (!inkCtx) return
      const s: Stroke = { ...INK, points: [] }
      if (!ink.has(index)) ink.set(index, [])
      ink.get(index)!.push(s)
      live.set(e.pointerId, s)
      const p = local(e)
      extend(inkCtx, s, p.x, p.y)
    })
    inkCanvas.addEventListener('pointermove', (e) => {
      const s = live.get(e.pointerId)
      if (!s || !inkCtx) return
      if (!e.buttons) return void live.delete(e.pointerId)
      const p = local(e)
      extend(inkCtx, s, p.x, p.y)
    })
    for (const ev of ['pointerup', 'pointercancel'] as const) inkCanvas.addEventListener(ev, (e) => live.delete(e.pointerId))

    return () => {
      alive = false
      rendering?.cancel()
      loading?.destroy()
      removeEventListener('keydown', onKey)
      offGesture()
    }
  },
}
