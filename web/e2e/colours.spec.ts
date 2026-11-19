// Guards the "no large saturated or dark fills" rule (see the top of src/style.css): the
// projector's colour sequence plus the camera's rolling shutter turns big strong areas into
// bands the engine mistakes for a hand. Thin outlines, text and small shapes are fine, so we
// look for solid blocks: fail if any square of at least BLOCK x BLOCK pixels is entirely
// "strong". Game screens are not checked: their sprites are small and allowed to be saturated.
import { expect, test, type Page } from '@playwright/test'
import { ENGINE } from './helpers'

const STRONG_SATURATION = 0.5 // HSV saturation above this is a strong colour...
const DARK_VALUE = 0.35 // ...and HSV value below this is dark (ink, black)
const BLOCK = 130 // px at 1920x1080, about 12 % of the height

/** Largest all-strong square on the page, via the classic maximal-square dynamic programme. */
async function largestStrongBlock(page: Page) {
  const png = await page.screenshot()
  return page.evaluate(
    async ([b64, sat, val]) => {
      const img = new Image()
      img.src = `data:image/png;base64,${b64}`
      await img.decode()
      const { width: w, height: h } = img
      const c = new OffscreenCanvas(w, h)
      const ctx = c.getContext('2d')!
      ctx.drawImage(img, 0, 0)
      const d = ctx.getImageData(0, 0, w, h).data
      let prev = new Uint16Array(w), best = { size: 0, x: 0, y: 0 }
      for (let y = 0; y < h; y++) {
        const row = new Uint16Array(w)
        for (let x = 0; x < w; x++) {
          const i = (y * w + x) * 4
          const max = Math.max(d[i], d[i + 1], d[i + 2]), min = Math.min(d[i], d[i + 1], d[i + 2])
          const strong = (max > 0 && (max - min) / max > sat) || max / 255 < val
          if (!strong) continue
          row[x] = x && y ? 1 + Math.min(row[x - 1], prev[x], prev[x - 1]) : 1
          if (row[x] > best.size) best = { size: row[x], x: x - row[x] + 1, y: y - row[x] + 1 }
        }
        prev = row
      }
      return best
    },
    [png.toString('base64'), STRONG_SATURATION, DARK_VALUE] as const,
  )
}

async function check(page: Page, what: string) {
  await page.waitForTimeout(400) // let pop/flip animations settle
  const b = await largestStrongBlock(page)
  expect(b.size, `${what}: a ${b.size}px strong block at (${b.x}, ${b.y})`).toBeLessThan(BLOCK)
}

test('no large saturated or dark fills on the launcher, quiz, memory, slides, settings and dialogs', async ({ page }) => {
  test.setTimeout(120_000)
  await page.goto(ENGINE)
  await expect(page.locator('.chip.ok')).toBeVisible()
  await check(page, 'launcher')

  await page.goto(`${ENGINE}/#quiz`)
  await check(page, 'quiz')
  for (let n = 0; n < 10; n++) {
    await page.locator('.answer').nth(n % 4).click()
    if (n === 0) await check(page, 'quiz answered')
    await page.locator('.quiz-next').click()
  }
  await expect(page.locator('.dialog')).toBeVisible()
  await check(page, 'quiz result')

  await page.goto(`${ENGINE}/#memory`)
  await check(page, 'memory')
  const keys = await page.locator('.card').evaluateAll((cs) => cs.map((c) => (c as HTMLElement).dataset.k))
  for (let k = 0; k < 6; k++) {
    for (const i of [keys.indexOf(String(k)), keys.lastIndexOf(String(k))]) await page.locator('.card').nth(i).click()
    if (k === 2) await check(page, 'memory half done')
  }
  await expect(page.locator('.dialog')).toBeVisible()
  await check(page, 'memory result')

  await page.goto(`${ENGINE}/#slides`)
  await expect(page.locator('.slides-num')).toHaveText('1 / 7')
  for (let i = 1; i <= 7; i++) {
    await expect(page.locator('.slides-num')).toHaveText(`${i} / 7`)
    await page.waitForTimeout(400) // pdf.js render
    await check(page, `slide ${i}`)
    await page.keyboard.press('ArrowRight')
  }

  await page.goto(`${ENGINE}/#settings`)
  await check(page, 'settings')
  await page.goto(`${ENGINE}/#balloons`)
  await check(page, 'balloons start dialog')
})
