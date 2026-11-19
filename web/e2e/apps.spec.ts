// Opens every app through the fake engine (hand input) and the mouse, with zero console errors.
import { expect, test } from '@playwright/test'
import { ENGINE, centre, engineSend, handStroke, handTap, handTapOn, holdHome, received, shot, state, watchErrors } from './helpers'

test('every app works by hand and by mouse', async ({ page, request }, info) => {
  test.setTimeout(180_000)
  const errors = watchErrors(page)
  await page.goto(ENGINE)
  await expect(page.locator('.chip.ok')).toContainText('Fake camera')
  await shot(page, info, '01-launcher')

  const open = async (id: string) => {
    await handTapOn(page, request, `.tile[data-go=${id}]`)
    await expect(page.locator('#view')).toHaveAttribute('data-app', id)
  }

  // Board: draw by hand and by mouse, change colour by hand.
  await open('board')
  await handTapOn(page, request, '.swatch[data-color="2"]')
  await expect(page.locator('.swatch[data-color="2"]')).toHaveClass(/on/)
  await handStroke(request, Array.from({ length: 30 }, (_, i) => [500 + i * 30, 400 + Math.sin(i / 3) * 120] as [number, number]))
  await page.mouse.move(600, 750)
  await page.mouse.down()
  for (let i = 0; i < 20; i++) await page.mouse.move(600 + i * 40, 750 - i * 10)
  await page.mouse.up()
  await handStroke(request, [[1300, 700], [1350, 720], [1400, 760], [1450, 760]], 2, 'palm') // palm erases
  const inked = await page.evaluate(() => {
    const c = document.querySelector<HTMLCanvasElement>('.board canvas')!
    const d = c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data
    let n = 0
    for (let i = 0; i < d.length; i += 4) if (d[i] < 200 || d[i + 1] < 200) n++
    return n
  })
  expect(inked).toBeGreaterThan(2000)
  // Save goes to the engine (the built-in window cannot download) and shows where it went.
  await handTapOn(page, request, '[data-act=save]')
  await expect(page.locator('.saved')).toContainText('Pictures/VisionTouch/board-')
  expect((await received(request)).filter((m) => m.t === 'save')).toContainEqual(expect.objectContaining({ name: 'board', png: true }))
  await shot(page, info, '02-board')
  await holdHome(page)

  // Balloons: start by hand, sweep the screen with mouse taps until something pops.
  await open('balloons')
  await shot(page, info, '03-balloons-start')
  await handTapOn(page, request, '.dialog .btn >> nth=0')
  await page.waitForTimeout(3500)
  await shot(page, info, '04-balloons-play')
  for (let y = 250; y <= 1000 && !(await page.locator('.hud').innerText()).includes('★ 1'); y += 110)
    for (let x = 260; x <= 1660; x += 110) {
      await page.mouse.click(x, y)
    }
  await expect(page.locator('.hud')).not.toContainText('★ 0')
  await holdHome(page)

  // Catch: mask subscription, a silhouette, mouse catching.
  await open('catch')
  await handTapOn(page, request, '.dialog .btn >> nth=0')
  const cells = new Uint8Array(64 * 36)
  for (let y = 10; y < 36; y++) for (let x = 26; x < 38; x++) cells[y * 64 + x] = 255
  for (let i = 0; i < 40; i++) {
    await engineSend(request, { t: 'mask', w: 64, h: 36, b64: Buffer.from(cells).toString('base64') })
    await page.mouse.move(400 + i * 25, 700)
    await page.waitForTimeout(60)
  }
  await shot(page, info, '05-catch')
  expect((await received(request)).some((m) => m.t === 'cmd' && m.name === 'subscribe_mask' && m.value === true)).toBe(true)
  await holdHome(page)
  expect((await received(request)).some((m) => m.t === 'cmd' && m.name === 'subscribe_mask' && m.value === false)).toBe(true)

  // Slides: sample deck, edge zone by hand, swipe gesture, keyboard, annotation.
  await open('slides')
  await expect(page.locator('.slides-num')).toHaveText('1 / 7')
  await handTapOn(page, request, '.edge.next')
  await expect(page.locator('.slides-num')).toHaveText('2 / 7')
  await engineSend(request, { t: 'gesture', name: 'swipe_left' })
  await expect(page.locator('.slides-num')).toHaveText('3 / 7')
  await page.keyboard.press('ArrowLeft')
  await expect(page.locator('.slides-num')).toHaveText('2 / 7')
  await handStroke(request, Array.from({ length: 20 }, (_, i) => [700 + i * 25, 800 - i * 8] as [number, number]))
  await page.waitForTimeout(300)
  await shot(page, info, '06-slides')
  await holdHome(page)

  // Quiz: answer by hand.
  await open('quiz')
  await shot(page, info, '07-quiz')
  await handTapOn(page, request, '.answer >> nth=0')
  await expect(page.locator('.answer.right')).toHaveCount(1)
  await expect(page.locator('.quiz-next')).toBeVisible()
  await page.waitForTimeout(500) // let the colour change finish
  await shot(page, info, '08-quiz-answered')
  await holdHome(page)

  // Memory: flip two cards (one by hand, one by mouse).
  await open('memory')
  await handTapOn(page, request, '.card >> nth=0')
  await page.locator('.card').nth(5).click()
  await expect(page.locator('.card.open')).toHaveCount(2)
  await page.waitForTimeout(300)
  await shot(page, info, '09-memory')
  await holdHome(page)

  // Accuracy: find each target on the canvas (its ink-coloured centre dot) and tap near it by hand.
  await open('accuracy')
  await shot(page, info, '10-accuracy-start')
  await handTapOn(page, request, '.dialog .btn')
  for (let i = 0; i < 20; i++) {
    await page.waitForTimeout(300)
    const [x, y] = await page.evaluate(() => {
      const c = document.querySelector<HTMLCanvasElement>('[data-app=accuracy] canvas')!
      const { width, height } = c
      const d = c.getContext('2d')!.getImageData(0, 0, width, height).data
      let sx = 0, sy = 0, n = 0
      for (let i = 0; i < d.length; i += 4)
        if (d[i] === 0x17 && d[i + 1] === 0x15 && d[i + 2] === 0x3b) {
          sx += (i / 4) % width
          sy += Math.floor(i / 4 / width)
          n++
        }
      return [sx / n, sy / n]
    })
    await handTap(request, x + (Math.random() - 0.5) * 30, y + (Math.random() - 0.5) * 30)
  }
  await expect(page.locator('.acc-summary')).toBeVisible()
  await shot(page, info, '11-accuracy-results')
  const logs = (await received(request)).filter((m) => m.t === 'log' && m.name === 'accuracy')
  expect(logs.length).toBeGreaterThanOrEqual(20)
  expect(logs.at(-1).data.error_pct_width).toBeLessThan(2)
  await holdHome(page)

  // Pipeline: engine connected but no live stages.
  await open('pipeline')
  await expect(page.locator('.placeholder').first()).toHaveText('This stage is not running')
  await holdHome(page)

  // Settings: live values and commands.
  await open('settings')
  await expect(page.locator('.settings dl')).toContainText('Fake camera')
  await handTapOn(page, request, '[data-cmd=calibrate]')
  // The keystone switch flips the engine's setting; the fake engine answers with a new state.
  const keystone = page.locator('[data-keystone]')
  await expect(keystone).toHaveAttribute('aria-checked', 'true')
  await handTapOn(page, request, '[data-keystone]')
  await expect(keystone).toHaveAttribute('aria-checked', 'false')
  await engineSend(request, state({ keystone: false, message: 'Calibrated: 48 markers, 1.3 px error, 110 ms delay, squared to the screen frame' }))
  await expect(page.locator('.engine-msg')).toContainText('1.3 px error')
  await shot(page, info, '13-settings')
  await keystone.click()
  await expect(keystone).toHaveAttribute('aria-checked', 'true')
  // Desktop mode: the stage turns into a single "back" button; pressing it returns to apps.
  await page.locator('[data-mode=desktop]').click()
  await expect(page.locator('#back')).toBeVisible()
  await expect(page.locator('#stage')).toBeHidden()
  await page.locator('#back').click()
  await expect(page.locator('#stage')).toBeVisible()
  const cmds = (await received(request)).filter((m) => m.t === 'cmd')
  expect(cmds).toContainEqual({ t: 'cmd', name: 'calibrate' })
  expect(cmds).toContainEqual({ t: 'cmd', name: 'keystone', value: false })
  expect(cmds).toContainEqual({ t: 'cmd', name: 'keystone', value: true })
  expect(cmds).toContainEqual({ t: 'cmd', name: 'mode', value: 'desktop' })
  expect(cmds).toContainEqual({ t: 'cmd', name: 'mode', value: 'apps' })
  await holdHome(page)

  // Home button: a short press must not leave the app.
  await open('quiz')
  const [hx, hy] = await centre(page, '#home')
  await page.mouse.click(hx, hy)
  await page.waitForTimeout(1200)
  await expect(page.locator('#view')).toHaveAttribute('data-app', 'quiz')

  expect(errors).toEqual([])
})
