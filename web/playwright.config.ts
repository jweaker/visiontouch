import { defineConfig, devices } from '@playwright/test'

// Headless only. Two servers over the built dist/: the fake engine (engine present)
// and a plain static server (engine absent). Never port 8765: that is the real engine's.
export default defineConfig({
  testDir: 'e2e',
  fullyParallel: false,
  workers: 1,
  use: { viewport: { width: 1920, height: 1080 }, headless: true },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 } },
    { name: 'webkit', use: { ...devices['Desktop Safari'], viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 } },
  ],
  webServer: [
    { command: 'node fake-engine.mjs --port 5198', url: 'http://127.0.0.1:5198/', reuseExistingServer: false },
    { command: 'pnpm exec vite preview --port 5197 --strictPort --host 127.0.0.1', url: 'http://127.0.0.1:5197/', reuseExistingServer: false },
  ],
})
