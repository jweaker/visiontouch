import { beforeEach, describe, expect, it } from 'vitest'
import { emit } from './engine'
import { handlePointers, hands, poseOf } from './pointers'

// happy-dom has no layout, so we decide which element is "under" a point ourselves:
// left half of the window → #a, right half → #b.
let log: string[]
beforeEach(() => {
  handlePointers([]) // forget hands from the previous test
  emit({ t: 'state', mode: 'apps' })
  const root = document.createElement('main') // fresh element per test so listeners don't pile up
  root.innerHTML = '<div id="a"></div><div id="b"></div>'
  document.body.replaceChildren(root)
  const a = document.getElementById('a')!, b = document.getElementById('b')!
  document.elementFromPoint = (x: number) => (x < innerWidth / 2 ? a : b)
  log = []
  for (const type of ['pointerdown', 'pointermove', 'pointerup', 'pointercancel', 'click']) {
    root.addEventListener(type, (e) => {
      const p = e as PointerEvent
      log.push(`${type}:${(e.target as Element).id}:${p.pointerId ?? ''}:${p.buttons ?? ''}`)
    })
  }
})

const hand = (id: number, x: number, down: boolean, pose = 'point') => ({ id, x, y: 0.5, down, pose }) as any

describe('pointer shim', () => {
  it('hover, down, up and click on the same element', () => {
    handlePointers([hand(1, 0.2, false)])
    handlePointers([hand(1, 0.21, true)])
    handlePointers([hand(1, 0.22, false)])
    expect(log).toEqual([
      'pointermove:a:1001:0',
      'pointerdown:a:1001:1',
      'pointerup:a:1001:0',
      'click:a::0',
    ])
  })

  it('touch is captured by the down target and a long drag to another element is not a click', () => {
    handlePointers([hand(1, 0.2, true)])
    handlePointers([hand(1, 0.8, true)])
    handlePointers([hand(1, 0.8, false)])
    expect(log).toEqual(['pointerdown:a:1001:1', 'pointermove:a:1001:1', 'pointerup:a:1001:0'])
  })

  it('two hands get separate, stable pointer ids', () => {
    handlePointers([hand(1, 0.2, true), hand(2, 0.7, true)])
    handlePointers([hand(1, 0.2, false), hand(2, 0.7, true)])
    expect(log.slice(0, 2)).toEqual(['pointerdown:a:1001:1', 'pointerdown:b:1002:1'])
    expect(log).toContain('pointerup:a:1001:0')
    expect(log).toContain('pointermove:b:1002:1')
    expect(hands.size).toBe(2)
  })

  it('a hand that disappears while down is cancelled and forgotten', () => {
    handlePointers([hand(3, 0.6, true, 'palm')])
    expect(poseOf(1003)).toBe('palm')
    handlePointers([])
    expect(log).toEqual(['pointerdown:b:1003:1', 'pointercancel:b:1003:0'])
    expect(hands.size).toBe(0)
    expect(document.querySelectorAll('.ring').length).toBe(0)
  })

  it('shows a ring per hand with a down state', () => {
    handlePointers([hand(1, 0.2, true), hand(2, 0.7, false)])
    const rings = [...document.querySelectorAll('.ring')]
    expect(rings.map((r) => r.classList.contains('down'))).toEqual([true, false])
  })

  it('does not dispatch DOM events in desktop mode', () => {
    emit({ t: 'state', mode: 'desktop' })
    handlePointers([hand(1, 0.2, true)])
    expect(log).toEqual([])
    expect(hands.size).toBe(1)
  })
})
