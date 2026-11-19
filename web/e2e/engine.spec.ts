// The shell end to end through a real WebSocket: hello, pointer shim + rings, pattern overlay, warp.
import { expect, test } from '@playwright/test'
import { ENGINE, W, H, engineSend, handTap, received, shot, watchErrors } from './helpers'

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
