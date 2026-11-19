// The shell end to end through a real WebSocket: hello, pointer shim + rings, pattern overlay, warp.
import { expect, test } from '@playwright/test'
import { ENGINE, W, H, engineSend, handTap, received, shot, state, watchErrors } from './helpers'

test.beforeEach(async ({ page }) => {
  await page.goto(ENGINE)
  await expect(page.locator('.chip.ok')).toBeVisible()
})

test('hello carries the window size', async ({ request }) => {
  expect(await received(request)).toContainEqual({ t: 'hello', w: W, h: H })
})

test('pointer rings follow hands and show the down state', async ({ page, request }, info) => {
  await engineSend(request, {
    t: 'pointers',
    p: [
      { id: 4, x: 0.25, y: 0.5, down: false, pose: 'point' },
      { id: 5, x: 0.75, y: 0.5, down: true, pose: 'point' },
      { id: 6, x: 0.6, y: 0.82, down: false, pose: 'palm' },
    ],
  })
  await expect(page.locator('.ring')).toHaveCount(3)
  await expect(page.locator('.ring.down')).toHaveCount(1)
  await expect(page.locator('.tile.hot')).toHaveCount(2) // hovering hands highlight what they point at
  await shot(page, info, '22-hand-rings')
  const box = (await page.locator('.ring.point:not(.down)').boundingBox())!
  expect(box.x + box.width / 2).toBeCloseTo(0.25 * W, -1)
  await engineSend(request, { t: 'pointers', p: [] })
  await expect(page.locator('.ring')).toHaveCount(0)
  await expect(page.locator('.hot')).toHaveCount(0)
})

test('pattern overlay: full window, 1:1, alone, acknowledged', async ({ page, request }, info) => {
  const errors = watchErrors(page)
  await engineSend(request, { t: 'pattern', id: 7, url: '/pattern/7.png' })
  await expect(page.locator('#pattern')).toBeVisible()
  await expect(page.locator('#stage')).toBeHidden()
  await expect.poll(async () => (await received(request)).some((m) => m.t === 'pattern_shown' && m.id === 7)).toBe(true)
  // The fake pattern is a checkerboard of 110 px cells at window size: check pixels land exactly.
  const png = await page.screenshot()
  await shot(page, info, '20-pattern')
  const pixel = await page.evaluate(async (b64) => {
    const img = new Image()
    img.src = `data:image/png;base64,${b64}`
    await img.decode()
    const c = new OffscreenCanvas(img.width, img.height)
    const ctx = c.getContext('2d')!
    ctx.drawImage(img, 0, 0)
    const at = (x: number, y: number) => ctx.getImageData(x, y, 1, 1).data[0]
    return [at(0, 0), at(109, 0), at(110, 0), at(109, 110), at(110, 110)]
  }, png.toString('base64'))
  expect(pixel).toEqual([0, 0, 255, 255, 0])
  await engineSend(request, { t: 'pattern', id: 8, url: null })
  await expect(page.locator('#pattern')).toBeHidden()
  await expect(page.locator('#stage')).toBeVisible()
  expect(errors).toEqual([])
})

test('warp keystones the content box and hands still hit the right element', async ({ page, request }, info) => {
  // Maps the content box into a trapezoid: top edge narrower than the bottom.
  const m = [0.8, -0.1, 300, 0, 0.7, 100, 0, -0.0001, 1]
  await engineSend(request, { t: 'warp', m })
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.getElementById('stage')!).transform)).toContain('matrix3d')
  await shot(page, info, '21-warped-launcher')

  const map = (x: number, y: number) => {
    const w = m[6] * x + m[7] * y + m[8]
    return [(m[0] * x + m[1] * y + m[2]) / w, (m[3] * x + m[4] * y + m[5]) / w]
  }
  // The browser's real hit test at the warped position of the content's bottom-right corner area.
  const [wx, wy] = map(W - 40, H - 40)
  const inStage = (x: number, y: number) => page.evaluate(([x, y]) => !!document.elementFromPoint(x, y)?.closest('#stage'), [x, y])
  expect(await inStage(wx, wy)).toBe(true)
  expect(await inStage(5, 5)).toBe(false) // (0, 0) now lands at (300, 100): the window corner is outside

  // A hand at the quiz tile's content position opens it, even though the tile is drawn elsewhere.
  const tile = await page.evaluate(() => {
    const el = document.querySelector<HTMLElement>('.tile[data-go=quiz]')!
    let x = el.offsetWidth / 2, y = el.offsetHeight / 2
    for (let e: HTMLElement | null = el; e && e.id !== 'stage'; e = e.offsetParent as HTMLElement) (x += e.offsetLeft), (y += e.offsetTop)
    return [x, y]
  })
  // Sanity: the ring is drawn at the warped spot.
  await engineSend(request, { t: 'pointers', p: [{ id: 1, x: tile[0] / W, y: tile[1] / H, down: false }] })
  const ring = (await page.locator('.ring').boundingBox())!
  const [ex, ey] = map(tile[0], tile[1])
  expect(Math.abs(ring.x + ring.width / 2 - ex)).toBeLessThan(3)
  expect(Math.abs(ring.y + ring.height / 2 - ey)).toBeLessThan(3)
  await handTap(request, tile[0], tile[1])
  await expect(page.locator('#view')).toHaveAttribute('data-app', 'quiz')

  await engineSend(request, { t: 'warp', m: null })
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.getElementById('stage')!).transform)).toBe('none')
})

test('a hand that disappears mid-press cancels instead of clicking', async ({ page, request }) => {
  const [x, y] = await page.evaluate(() => {
    const r = document.querySelector('.tile[data-go=memory]')!.getBoundingClientRect()
    return [r.x + r.width / 2, r.y + r.height / 2]
  })
  await page.evaluate(() => {
    ;(window as any).seen = []
    for (const t of ['pointerdown', 'pointercancel', 'click']) document.addEventListener(t, (e) => (window as any).seen.push(e.type))
  })
  await engineSend(request, { t: 'pointers', p: [{ id: 9, x: x / W, y: y / H, down: true }] })
  await engineSend(request, { t: 'pointers', p: [] })
  await expect.poll(() => page.evaluate(() => (window as any).seen)).toEqual(['pointerdown', 'pointercancel'])
  await expect(page.locator('#view')).toHaveAttribute('data-app', 'home')
})

test('the outside of the keystoned content box is black, the box itself is paper', async ({ page, request }) => {
  await engineSend(request, { t: 'warp', m: [0.8, 0, 192, 0, 0.8, 108, 0, 0, 1] })
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.getElementById('stage')!).transform)).toContain('matrix')
  const png = await page.screenshot()
  const [outside, inside] = await page.evaluate(async (b64) => {
    const img = new Image()
    img.src = `data:image/png;base64,${b64}`
    await img.decode()
    const c = new OffscreenCanvas(img.width, img.height)
    const ctx = c.getContext('2d')!
    ctx.drawImage(img, 0, 0)
    const at = (x: number, y: number) => [...ctx.getImageData(x, y, 1, 1).data.slice(0, 3)]
    return [at(20, 20), at(960, 1010)] // window corner; inside the box below the tiles (footer line)
  }, png.toString('base64'))
  expect(outside).toEqual([0, 0, 0])
  expect(Math.min(...inside)).toBeGreaterThan(200)
  await engineSend(request, { t: 'warp', m: null })
})

test('the cursor ring fills while a pointing hand holds still', async ({ page, request }, info) => {
  const dwell = () => page.evaluate(() => Number(document.querySelector<HTMLElement>('.ring')!.style.getPropertyValue('--dwell')))
  const hold = (x: number) => engineSend(request, { t: 'pointers', p: [{ id: 2, x, y: 0.93, down: false, pose: 'point' }] })
  await hold(0.5)
  await page.waitForTimeout(500)
  await hold(0.505) // jitter inside the 2.5 % radius keeps the anchor
  const half = await dwell()
  expect(half).toBeGreaterThan(0.4)
  expect(half).toBeLessThan(1)
  await shot(page, info, '23-dwell-ring')
  await hold(0.6) // moved: starts over
  expect(await dwell()).toBeLessThan(0.1)
  await engineSend(request, { t: 'pointers', p: [] })
})

test('calibration progress shows as a big toast on any screen', async ({ page, request }, info) => {
  await engineSend(request, state({ message: 'Calibrating: finding the screen' }))
  await expect(page.locator('#toast')).toHaveText('Calibrating: finding the screen')
  await shot(page, info, '24-calibrating-toast')
  await engineSend(request, state({ message: 'Calibration failed: the camera must see the whole projected picture' }))
  await expect(page.locator('#toast')).toBeHidden()
  await page.goto(`${ENGINE}/#settings`)
  await engineSend(request, state({ message: 'Calibration failed: the camera must see the whole projected picture' }))
  await expect(page.locator('.engine-msg.bad')).toContainText('Calibration failed')
  await engineSend(request, state())
})

test('desktop mode: only a back button in the small strip, warp ignored', async ({ page, request }, info) => {
  const errors = watchErrors(page)
  await engineSend(request, { t: 'warp', m: [0.8, 0, 192, 0, 0.8, 108, 0, 0, 1] })
  await page.setViewportSize({ width: 420, height: 110 })
  await engineSend(request, state({ mode: 'desktop' }))
  await expect(page.locator('#back')).toBeVisible()
  await expect(page.locator('#stage')).toBeHidden()
  await engineSend(request, { t: 'pointers', p: [{ id: 1, x: 0.5, y: 0.5, down: false, pose: 'point' }] })
  await expect(page.locator('.rings')).toBeHidden()
  expect(await page.evaluate(() => getComputedStyle(document.getElementById('stage')!).transform)).toBe('none')
  const box = (await page.locator('#back').boundingBox())!
  expect([box.width, box.height]).toEqual([420, 110])
  // The label fits on one line, unclipped.
  expect(await page.locator('#back').evaluate((b) => b.scrollWidth <= b.clientWidth && b.scrollHeight <= b.clientHeight)).toBe(true)
  await shot(page, info, '25-desktop-strip')
  await page.locator('#back').click() // the fake engine switches back to apps
  await expect.poll(async () => (await received(request)).some((m) => m.t === 'cmd' && m.name === 'mode' && m.value === 'apps')).toBe(true)
  await page.setViewportSize({ width: W, height: H })
  await expect(page.locator('#stage')).toBeVisible()
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.getElementById('stage')!).transform)).toContain('matrix') // warp is back
  await engineSend(request, { t: 'warp', m: null })
  await engineSend(request, { t: 'pointers', p: [] })
  expect(errors).toEqual([])
})

test('pipeline streams only the listed stages and closes them on leaving', async ({ page, request }, info) => {
  const streams = async () => (await request.get(`${ENGINE}/fake/streams`)).json()
  await request.post(`${ENGINE}/fake/stages`, { data: JSON.stringify(['camera', 'residual', 'mask']) })
  try {
    await page.goto(`${ENGINE}/#pipeline`)
    await expect(page.locator('.stages img')).toHaveCount(3)
    await expect(page.locator('figure[data-stage=camera] img')).toBeVisible()
    await expect(page.locator('figure[data-stage=predicted] .placeholder')).toHaveText('This stage is not running')
    await expect.poll(streams).toBe(3)
    // Pipeline order, left to right and top to bottom.
    expect(await page.locator('figure').evaluateAll((f) => f.map((e) => (e as HTMLElement).dataset.stage))).toEqual([
      'camera', 'rectified', 'predicted', 'residual', 'mask', 'overlay',
    ])
    await shot(page, info, '12-pipeline')
    await page.evaluate(() => (location.hash = ''))
    await expect.poll(streams).toBe(0)
  } finally {
    await request.post(`${ENGINE}/fake/stages`, { data: '[]' })
  }
})
