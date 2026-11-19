// A stand-in for the Python engine, for testing the stage without a camera.
// Serves web/dist and speaks docs/protocol.md over /ws.
//
//   node fake-engine.mjs --port 5198 --demo   then open http://127.0.0.1:5198/
//
// --demo plays a loop: a hand circling (pressing every few seconds), a calibration pattern,
// then a keystone warp. Tests drive it instead through two extra endpoints:
//   POST /fake/send      body = one protocol message (JSON), broadcast to every stage
//   GET  /fake/received  every message the stages sent us, as a JSON array
import http from 'node:http'
import fs from 'node:fs'
import path from 'node:path'
import zlib from 'node:zlib'
import { WebSocketServer } from 'ws'

const args = process.argv.slice(2)
const port = Number(args[args.indexOf('--port') + 1]) || 5198
if (port === 8765) throw new Error('8765 belongs to the real engine')
const demo = args.includes('--demo')
const root = path.join(path.dirname(new URL(import.meta.url).pathname), 'dist')
const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.pdf': 'application/pdf', '.woff2': 'font/woff2', '.woff': 'font/woff', '.png': 'image/png', '.json': 'application/json' }

const received = []
let size = { w: 1920, h: 1080 }

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://x')
  if (url.pathname === '/fake/send' && req.method === 'POST') {
    let body = ''
    for await (const chunk of req) body += chunk
    broadcast(JSON.parse(body))
    return res.end('ok')
  }
  if (url.pathname === '/fake/received') return json(res, received)
  if (url.pathname === '/debug/stages') return json(res, [])
  const pattern = url.pathname.match(/^\/pattern\/(\d+)\.png$/)
  if (pattern) {
    res.writeHead(200, { 'content-type': 'image/png' })
    return res.end(checkerboard(size.w, size.h, 40 + Number(pattern[1]) * 10))
  }
  const file = path.join(root, url.pathname === '/' ? 'index.html' : path.normalize(url.pathname))
  if (!file.startsWith(root) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
    res.writeHead(404)
    return res.end('not found')
  }
  res.writeHead(200, { 'content-type': types[path.extname(file)] ?? 'application/octet-stream' })
  fs.createReadStream(file).pipe(res)
})

const json = (res, data) => {
  res.writeHead(200, { 'content-type': 'application/json' })
  res.end(JSON.stringify(data))
}

const wss = new WebSocketServer({ server, path: '/ws' })
const broadcast = (msg) => wss.clients.forEach((c) => c.send(JSON.stringify(msg)))
wss.on('connection', (ws) => {
  ws.on('message', (data) => {
    const msg = JSON.parse(String(data))
    received.push(msg)
    if (msg.t === 'hello') size = { w: msg.w, h: msg.h }
  })
  ws.send(JSON.stringify({ t: 'state', calibrated: true, camera: 'Fake camera', fps: 30, latency_ms: 95, mode: 'apps', message: '' }))
})

// Grayscale checkerboard PNG, written by hand so we need no image library.
function checkerboard(w, h, cell) {
  const raw = Buffer.alloc((w + 1) * h)
  for (let y = 0; y < h; y++) {
    raw[y * (w + 1)] = 0 // filter: none
    for (let x = 0; x < w; x++) raw[y * (w + 1) + 1 + x] = (Math.floor(x / cell) + Math.floor(y / cell)) % 2 ? 255 : 0
  }
  const chunk = (type, data) => {
    const len = Buffer.alloc(4)
    len.writeUInt32BE(data.length)
    const td = Buffer.concat([Buffer.from(type), data])
    const crc = Buffer.alloc(4)
    crc.writeUInt32BE(zlib.crc32(td))
    return Buffer.concat([len, td, crc])
  }
  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(w, 0)
  ihdr.writeUInt32BE(h, 4)
  ihdr[8] = 8 // bit depth
  ihdr[9] = 0 // grayscale
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', zlib.deflateSync(raw)),
    chunk('IEND', Buffer.alloc(0)),
  ])
}

if (demo) {
  const t0 = Date.now()
  setInterval(() => {
    const t = (Date.now() - t0) / 1000
    const phase = t % 20 // 0-12 s: circling hand, 12-14 s: pattern, 14-20 s: warped
    if (phase < 12 || phase >= 14) {
      const x = 0.5 + 0.3 * Math.cos(t), y = 0.5 + 0.3 * Math.sin(t)
      broadcast({ t: 'pointers', p: [{ id: 1, x, y, down: t % 3 < 1, pose: 'point' }] })
    }
  }, 33)
  let step = 0
  setInterval(() => {
    const phase = step++ % 20
    broadcast({ t: 'state', calibrated: true, camera: 'Fake camera', fps: 30, latency_ms: 95, mode: 'apps', message: '' })
    if (phase === 12) broadcast({ t: 'pattern', id: 7, url: '/pattern/7.png' })
    if (phase === 14) {
      broadcast({ t: 'pattern', id: 8, url: null })
      broadcast({ t: 'warp', m: [0.9, 0.05, 60, -0.02, 0.92, 40, 0, 0.00004, 1] })
    }
    if (phase === 0) broadcast({ t: 'warp', m: null })
  }, 1000)
}

server.listen(port, '127.0.0.1', () => console.log(`fake engine on http://127.0.0.1:${port}/${demo ? ' (demo)' : ''}`))
