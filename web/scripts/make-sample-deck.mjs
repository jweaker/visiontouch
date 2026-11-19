// Regenerates public/sample-deck.pdf (the deck Slides opens by default) with headless Chromium.
// Run: node scripts/make-sample-deck.mjs
// No large saturated or dark shapes (see src/style.css): big areas are light tints, the strong
// colour is only in outlines and small accents.
import { chromium } from '@playwright/test'
import { fileURLToPath } from 'node:url'
import { readFileSync } from 'node:fs'

// Fonts as data URLs: a page made with setContent may not load file:// URLs.
const font = (p) => `data:font/woff2;base64,${readFileSync(new URL(`../node_modules/${p}`, import.meta.url)).toString('base64')}`
const slides = [
  ['VisionTouch', 'Smart Projector Board', 'Any projector + any camera = a touch screen.', '#2F5BFF'],
  ['The idea', 'Touch the wall', 'A camera watches the picture. Where your hand covers it, that is where you touched.', '#FF5A36'],
  ['1 · Calibrate', 'Find the screen', 'Project known patterns, find them in the camera image, compute a homography (4+ point pairs).', '#17C38C'],
  ['2 · Predict', 'What should the camera see?', 'We know what we project, so we can predict the camera image without a hand.', '#FFC93C'],
  ['3 · Subtract', 'Find what is new', 'Camera minus prediction, threshold, morphology: the mask shows your hand and arm.', '#FF4FA3'],
  ['4 · Act', 'Point, pinch, palm, swipe', 'Fingertip = cursor. Pinch = click. Open palm = erase. Swipe = next slide.', '#38C6FF'],
  ['Try it', 'Draw on this slide', 'Press and draw. Tap the edges or swipe to change slides.', '#2F5BFF'],
]

const html = `<!doctype html><html><head><style>
@font-face { font-family: Display; src: url('${font('@fontsource-variable/bricolage-grotesque/files/bricolage-grotesque-latin-wght-normal.woff2')}'); font-weight: 200 800; }
@font-face { font-family: Body; src: url('${font('@fontsource/atkinson-hyperlegible/files/atkinson-hyperlegible-latin-400-normal.woff2')}'); }
@page { size: 1920px 1080px; margin: 0; }
body { margin: 0; }
section { width: 1920px; height: 1080px; box-sizing: border-box; padding: 120px 150px; background: #FFF6E6; color: #17153B;
  position: relative; overflow: hidden; break-after: page; font-family: Body; }
.tag { display: inline-block; padding: 12px 34px; border: 6px solid #17153B; border-radius: 999px;
  background: color-mix(in srgb, var(--c) 22%, #fff); box-shadow: inset 0 0 0 8px var(--c); font: 800 44px Display; }
h1 { font: 800 150px/1 Display; letter-spacing: -0.04em; margin: 60px 0 40px; }
p { font-size: 58px; line-height: 1.25; max-width: 1400px; margin: 0; }
.blob { position: absolute; right: -140px; bottom: -140px; width: 560px; height: 560px; border-radius: 50%;
  border: 8px solid #17153B; background: color-mix(in srgb, var(--c) 22%, #fff); box-shadow: inset 0 0 0 36px var(--c); }
.blob::after { content: ''; position: absolute; inset: 150px; border-radius: 50%; border: 36px solid var(--c); }
</style></head><body>${slides
  .map(([tag, title, text, c]) => `<section style="--c:${c}"><span class="tag">${tag}</span><h1>${title}</h1><p>${text}</p><div class="blob"></div></section>`)
  .join('')}</body></html>`

const browser = await chromium.launch()
const page = await browser.newPage()
await page.setContent(html, { waitUntil: 'networkidle' })
await page.pdf({ path: fileURLToPath(new URL('../public/sample-deck.pdf', import.meta.url)), width: '1920px', height: '1080px', printBackground: true })
await browser.close()
console.log('wrote public/sample-deck.pdf')
