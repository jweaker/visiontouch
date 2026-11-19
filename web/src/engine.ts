// The one WebSocket to the Python engine (see docs/protocol.md).
// When the engine is absent we keep retrying quietly; the stage still works with a mouse.

export interface EngineState {
  calibrated: boolean
  camera: string
  fps: number
  latency_ms: number
  mode: 'apps' | 'desktop'
  keystone: boolean
  sensitivity?: number // detection sensitivity, 1 = default
  message: string
}

type Handler = (msg: any) => void
const handlers = new Map<string, Set<Handler>>()
let ws: WebSocket | null = null

export const engine = { connected: false, state: null as EngineState | null }

/** Listen for one message type (`pointers`, `state`, ...). Returns an "unlisten" function. */
export function on(type: string, fn: Handler): () => void {
  if (!handlers.has(type)) handlers.set(type, new Set())
  handlers.get(type)!.add(fn)
  return () => handlers.get(type)!.delete(fn)
}

/** Deliver a message to listeners. Used for engine messages and by tests. */
export function emit(msg: { t: string; [k: string]: any }) {
  if (msg.t === 'state') engine.state = msg as any
  handlers.get(msg.t)?.forEach((fn) => fn(msg))
}

export function send(msg: { t: string; [k: string]: any }) {
  if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg))
}

const hello = () => send({ t: 'hello', w: innerWidth, h: innerHeight })

export function connect() {
  if (!location.host) return // opened from file://, no engine possible
  const url = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`
  let delay = 500
  const open = () => {
    ws = new WebSocket(url)
    ws.onopen = () => {
      delay = 500
      engine.connected = true
      hello()
      emit({ t: 'connection' })
    }
    ws.onmessage = (e) => {
      try {
        emit(JSON.parse(e.data))
      } catch {
        // ignore malformed messages
      }
    }
    ws.onclose = () => {
      if (engine.connected) {
        engine.connected = false
        engine.state = null
        emit({ t: 'connection' })
      }
      setTimeout(open, delay)
      delay = Math.min(delay * 2, 8000)
    }
  }
  open()
  addEventListener('resize', hello)
}
