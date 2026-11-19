import { defineConfig } from 'vitest/config'

export default defineConfig({
  base: '/',
  build: {
    target: 'es2022',
    chunkSizeWarningLimit: 1500,
    rolldownOptions: {
      output: {
        // pdf.js ships its worker as .mjs; plain static servers may not know that MIME type,
        // and module workers refuse non-JavaScript types. Emit it as .js instead.
        assetFileNames: (a) => (a.names[0]?.endsWith('.mjs') ? 'assets/[name]-[hash].js' : 'assets/[name]-[hash][extname]'),
      },
    },
  },
  server: { port: 5199, strictPort: true },
  test: { environment: 'happy-dom', include: ['src/**/*.test.ts'] },
})
