// No engine at all: a plain static server. Everything must still work with the mouse.
import { expect, test } from '@playwright/test'
import { STATIC, holdHome, watchErrors } from './helpers'

test('works with a mouse when the engine is absent', async ({ page }) => {
  const errors = watchErrors(page)
  await page.goto(STATIC)
  await expect(page.locator('.chip.off')).toContainText('Engine offline')
  for (const id of ['board', 'balloons', 'catch', 'slides', 'quiz', 'memory', 'accuracy', 'pipeline', 'settings']) {
    await page.locator(`.tile[data-go=${id}]`).click()
    await expect(page.locator('#view')).toHaveAttribute('data-app', id)
    await page.mouse.move(900, 600)
    await page.mouse.down()
    await page.mouse.move(1000, 650)
    await page.mouse.up()
    if (id === 'slides') await expect(page.locator('.slides-num')).toHaveText('1 / 7')
    if (id === 'pipeline') await expect(page.locator('.placeholder').first()).toHaveText('Waiting for the engine…')
    if (id === 'settings') await expect(page.locator('[data-cmd=calibrate]')).toBeDisabled()
    if (id === 'board') {
      // No engine to POST to: Save falls back to a download.
      const download = page.waitForEvent('download')
      await page.locator('[data-act=save]').click()
      expect((await download).suggestedFilename()).toMatch(/^visiontouch-board-\d+\.png$/)
    }
    await holdHome(page)
  }
  // The only acceptable noise is the browser reporting that /ws and /save (the engine's) are not there.
  expect(errors.filter((e) => !/WebSocket|\/ws\b|\/save\//.test(e))).toEqual([])
})
