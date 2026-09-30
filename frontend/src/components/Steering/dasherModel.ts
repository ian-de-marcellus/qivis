/**
 * The geometry of steering, Dasher-style.
 *
 * Every distribution is a column [0, 1] divided among its likeliest next
 * tokens, top to bottom by probability, each as tall as its probability.
 * Probability not among them is left as empty space at the bottom (it can
 * only be reached by typing). The view is a point on that column (c, the
 * world y under the crosshair) and a zoom (s, pixels per unit). Arriving at a
 * box zooms it to fill the view; entering it then makes its distribution the
 * column, with the picture unchanged. Backing out is the exact inverse.
 */

import type { TokenCandidate } from '../../api/types.ts'

export interface Box extends TokenCandidate {
  rank: number
  /** Top and bottom within the parent column, 0..1 */
  a: number
  b: number
}

export interface View {
  c: number
  s: number
}

export function layout(candidates: TokenCandidate[]): Box[] {
  const sorted = [...candidates].sort((x, y) => y.prob - x.prob)
  let a = 0
  return sorted.map((cand, rank) => {
    const box = { ...cand, rank, a, b: a + cand.prob }
    a = box.b
    return box
  })
}

/** The box a world y falls in, if any (not the unlisted remainder). */
export function boxAt(boxes: Box[], y: number): Box | undefined {
  return boxes.find((box) => y >= box.a && y < box.b)
}

/** Go into a box: its interval becomes the whole column, the picture unchanged. */
export function enter(view: View, box: Box): View {
  const h = box.b - box.a
  return { c: (view.c - box.a) / h, s: view.s * h }
}

/** Come back out of a box into its parent column (the inverse of enter). */
export function exit(view: View, box: Box): View {
  const h = box.b - box.a
  return { c: box.a + view.c * h, s: view.s / h }
}

export interface Steer {
  /** Where the pointer is, as a world y in the current column */
  targetY: number
  /** Zoom rate, natural-log units per second: > 0 forward, < 0 back */
  rate: number
  dt: number
}

/** One frame of motion: drift toward the pointer, zoom by the rate. */
export function advance(view: View, steer: Steer, gain = 3): View {
  const pull = Math.min(1, gain * steer.dt)
  const c = Math.min(1, Math.max(0, view.c + (steer.targetY - view.c) * pull))
  return { c, s: view.s * Math.exp(steer.rate * steer.dt) }
}

/** Screen y of a world y. */
export function screenY(view: View, y: number, crossY: number): number {
  return crossY + (y - view.c) * view.s
}

/** A token's text as it should read on a box: spaces and newlines made visible. */
export function tokenLabel(token: string): string {
  return token.replace(/\n/g, '↵').replace(/^ /, '·').replace(/ /g, '·')
}

/** Pointer-paced travel: left of the line backs up, a band just right of it
 *  holds (read and decide), and further right goes faster, gently at first. */
export function zones(crossX: number, W: number) {
  return { holdL: crossX - 16, holdR: crossX + (W - crossX) * 0.18 }
}

export function throttle(x: number, crossX: number, W: number): number {
  const { holdL, holdR } = zones(crossX, W)
  if (x < holdL) return -Math.min(1, (holdL - x) / Math.max(40, holdL))
  if (x <= holdR) return 0
  return Math.min(1, (x - holdR) / (W - holdR)) ** 1.6
}

/**
 * Only the options that are words (a letter, after an optional leading space),
 * and the turn's end, with probabilities renormalized among them: the
 * distribution given the next token is a word. What's shown, not what's
 * recorded (the record keeps the model's own probabilities).
 */
export function wordsOnly(candidates: TokenCandidate[], keep: string[] = []): TokenCandidate[] {
  const kept = candidates.filter((c) => /^\s?\p{L}/u.test(c.token) || keep.includes(c.token))
  const total = kept.reduce((sum, c) => sum + c.prob, 0) || 1
  return kept.map((c) => ({ ...c, prob: c.prob / total, raw_prob: c.raw_prob ?? c.prob, conditional: true }))
}
