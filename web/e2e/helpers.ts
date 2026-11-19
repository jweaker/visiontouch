import { expect, type APIRequestContext, type Page, type TestInfo } from '@playwright/test'

export const ENGINE = 'http://127.0.0.1:5198'
export const STATIC = 'http://127.0.0.1:5197'
export const W = 1920, H = 1080

/** Collect console errors and uncaught exceptions. */
export function watchErrors(page: Page) {
  const errors: string[] = []
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
  page.on('pageerror', (e) => errors.push(String(e)))
  return errors
}

/** Send one protocol message from the fake engine to the stage. */
export async function engineSend(request: APIRequestContext, msg: object) {
  const res = await request.post(`${ENGINE}/fake/send`, { data: JSON.stringify(msg) })
  expect(res.ok()).toBeTruthy()
}

export async function received(request: APIRequestContext): Promise<any[]> {
  return (await request.get(`${ENGINE}/fake/received`)).json()
}

/** A full engine state message with the fake engine's defaults. */
export const state = (o: object = {}) => ({ t: 'state', calibrated: true, camera: 'Fake camera', fps: 30, latency_ms: 95, mode: 'apps', keystone: true, message: '', ...o })

const frame = () => new Promise((r) => setTimeout(r, 40)) // engine sends ~30 messages/s

/** A hand at content-box pixel positions: hover, press, (move), release. */
export async function handTap(request: APIRequestContext, x: number, y: number, id = 1) {
  const p = (down: boolean) => ({ t: 'pointers', p: [{ id, x: x / W, y: y / H, down, pose: 'point' }] })
  for (const down of [false, true, true, false]) {
    await engineSend(request, p(down))
    await frame()
  }
  await engineSend(request, { t: 'pointers', p: [] })
}

export async function handStroke(request: APIRequestContext, pts: [number, number][], id = 1, pose = 'point') {
  for (const [i, [x, y]] of pts.entries()) {
    await engineSend(request, { t: 'pointers', p: [{ id, x: x / W, y: y / H, down: i < pts.length - 1, pose }] })
    await frame()
  }
  await engineSend(request, { t: 'pointers', p: [] })
}

/** Centre of an element in window pixels (identity warp → also content pixels). */
export async function centre(page: Page, selector: string) {
  const box = (await page.locator(selector).first().boundingBox())!
  return [box.x + box.width / 2, box.y + box.height / 2] as [number, number]
}

export async function handTapOn(page: Page, request: APIRequestContext, selector: string) {
  const [x, y] = await centre(page, selector)
  await handTap(request, x, y)
}

/** Hold the home button with the mouse for longer than a second. */
export async function holdHome(page: Page) {
  const [x, y] = await centre(page, '#home')
  await page.mouse.move(x, y)
  await page.mouse.down()
  await page.waitForTimeout(1200)
  await page.mouse.up()
  await expect(page.locator('#view')).toHaveAttribute('data-app', 'home')
}

export async function shot(page: Page, info: TestInfo, name: string) {
  if (info.project.name === 'chromium') await page.screenshot({ path: `screenshots/${name}.png` })
}
