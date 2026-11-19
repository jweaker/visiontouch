// Keystone correction. The engine sends a 3x3 homography H (row-major) that maps
// content-box pixels to window pixels. We apply it to the content box with CSS and
// keep H and its inverse so pointer positions can be converted both ways.

export type Mat3 = number[]
const IDENTITY: Mat3 = [1, 0, 0, 0, 1, 0, 0, 0, 1]
let H = IDENTITY
let Hinv = IDENTITY

/** Map (x, y) through a homography: the homogeneous divide is what makes it a "perspective" map. */
export function apply(m: Mat3, x: number, y: number): [number, number] {
  const w = m[6] * x + m[7] * y + m[8]
  return [(m[0] * x + m[1] * y + m[2]) / w, (m[3] * x + m[4] * y + m[5]) / w]
}

/** Inverse of a 3x3 matrix (adjugate / determinant). */
export function invert(m: Mat3): Mat3 {
  const [a, b, c, d, e, f, g, h, i] = m
  const A = e * i - f * h, B = f * g - d * i, C = d * h - e * g
  const det = a * A + b * B + c * C
  return [A, c * h - b * i, b * f - c * e, B, a * i - c * g, c * d - a * f, C, b * g - a * h, a * e - b * d].map(
    (v) => v / det,
  )
}

/**
 * CSS matrix3d for a 3x3 homography. A 2D point (x, y) is (x, y, 0, 1) in CSS, so the
 * homography goes in the x, y and w rows/columns and z passes through untouched.
 * matrix3d() lists the 4x4 matrix column by column. Needs transform-origin: 0 0.
 */
export function toMatrix3d(m: Mat3): string {
  const [a, b, c, d, e, f, g, h, i] = m
  return `matrix3d(${[a, d, 0, g, b, e, 0, h, 0, 0, 1, 0, c, f, 0, i].join(',')})`
}

/** Set the current warp (null = identity). Scaled so H[8] = 1: CSS clips points with w <= 0. */
export function setWarp(m: Mat3 | null) {
  H = m ? m.map((v) => v / m[8]) : IDENTITY
  Hinv = invert(H)
  return H
}

export const toWindow = (x: number, y: number) => apply(H, x, y)
export const toContent = (x: number, y: number) => apply(Hinv, x, y)

/** Pointer position in content-box pixels (what apps draw in), for mouse and hand alike. */
export function contentPoint(e: { clientX: number; clientY: number }) {
  const [x, y] = toContent(e.clientX, e.clientY)
  return { x, y }
}
