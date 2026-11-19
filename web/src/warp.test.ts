import { describe, expect, it } from 'vitest'
import { apply, invert, setWarp, toContent, toMatrix3d, toWindow } from './warp'

// A keystone that maps the 1920x1080 content box onto this window quad (clockwise from top-left).
const W = 1920, H = 1080
const quad = [[100, 50], [1800, 120], [1700, 1000], [200, 1040]]

// Solve the homography from 4 point pairs (standard 8x8 DLT with h22 = 1) to get a known H.
function homography(src: number[][], dst: number[][]) {
  const A: number[][] = []
  src.forEach(([x, y], k) => {
    const [u, v] = dst[k]
    A.push([x, y, 1, 0, 0, 0, -u * x, -u * y, u])
    A.push([0, 0, 0, x, y, 1, -v * x, -v * y, v])
  })
  for (let c = 0; c < 8; c++) {
    const p = A.reduce((best, r, i) => (i >= c && Math.abs(r[c]) > Math.abs(A[best][c]) ? i : best), c)
    ;[A[c], A[p]] = [A[p], A[c]]
    for (let r = 0; r < 8; r++) if (r !== c) {
      const f = A[r][c] / A[c][c]
      for (let k = c; k < 9; k++) A[r][k] -= f * A[c][k]
    }
  }
  return [...A.map((r, i) => r[8] / r[i]), 1]
}

// Apply a CSS matrix3d(...) string the way the browser does: column-major 4x4 times (x, y, 0, 1).
function cssApply(css: string, x: number, y: number) {
  const n = css.slice(9, -1).split(',').map(Number)
  const col = (r: number) => n[r] * x + n[4 + r] * y + n[8 + r] * 0 + n[12 + r]
  return [col(0) / col(3), col(1) / col(3)]
}

const corners = [[0, 0], [W, 0], [W, H], [0, H]]

describe('warp', () => {
  const m = homography(corners, quad)

  it('the test homography maps the corners onto the quad', () => {
    corners.forEach(([x, y], k) => {
      const [u, v] = apply(m, x, y)
      expect(u).toBeCloseTo(quad[k][0], 6)
      expect(v).toBeCloseTo(quad[k][1], 6)
    })
  })

  it('matrix3d sends content corners to the same window points', () => {
    const css = toMatrix3d(m)
    corners.forEach(([x, y], k) => {
      const [u, v] = cssApply(css, x, y)
      expect(u).toBeCloseTo(quad[k][0], 6)
      expect(v).toBeCloseTo(quad[k][1], 6)
    })
    // an interior point too
    const [u, v] = cssApply(css, 700, 300)
    const [eu, ev] = apply(m, 700, 300)
    expect(u).toBeCloseTo(eu, 6)
    expect(v).toBeCloseTo(ev, 6)
  })

  it('scale of H does not matter and negative scale is normalised', () => {
    const scaled = setWarp(m.map((v) => v * -3))
    expect(scaled[8]).toBe(1)
    const [u, v] = toWindow(W, H)
    expect(u).toBeCloseTo(quad[2][0], 6)
    expect(v).toBeCloseTo(quad[2][1], 6)
  })

  it('toContent inverts toWindow', () => {
    setWarp(m)
    const [x, y] = toContent(...toWindow(123, 456))
    expect(x).toBeCloseTo(123, 6)
    expect(y).toBeCloseTo(456, 6)
    const I = invert(invert(m))
    I.forEach((v, i) => expect(v).toBeCloseTo(m[i], 6))
    setWarp(null)
    expect(toWindow(5, 7)).toEqual([5, 7])
  })
})
