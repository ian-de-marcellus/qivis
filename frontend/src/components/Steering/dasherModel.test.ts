import { describe, expect, it } from 'vitest'
import { advance, boxAt, enter, exit, layout, screenY, throttle, tokenLabel } from './dasherModel.ts'

const cands = [
  { id: 2, token: ' b', bytes: null, prob: 0.25 },
  { id: 1, token: 'a', bytes: null, prob: 0.6 },
  { id: 3, token: '\n', bytes: null, prob: 0.1 },
]

describe('dasher geometry', () => {
  const boxes = layout(cands)

  it('stacks tokens by probability, leaving unlisted mass at the bottom', () => {
    expect(boxes.map((b) => [b.token, b.rank])).toEqual([['a', 0], [' b', 1], ['\n', 2]])
    expect(boxes[0].a).toBe(0)
    expect(boxes[2].b).toBeCloseTo(0.95)
    expect(boxAt(boxes, 0.7)?.token).toBe(' b')
    expect(boxAt(boxes, 0.97)).toBeUndefined() // the unlisted remainder
  })

  it('entering then exiting a box returns the same picture', () => {
    const view = { c: 0.7, s: 900 }
    const box = boxes[1]
    const inside = enter(view, box)
    // The point under the crosshair and its screen position don't jump
    expect(screenY(inside, inside.c, 500)).toBeCloseTo(screenY(view, view.c, 500))
    expect(inside.s).toBeCloseTo(900 * 0.25)
    const back = exit(inside, box)
    expect(back.c).toBeCloseTo(view.c)
    expect(back.s).toBeCloseTo(view.s)
  })

  it('drifts toward the pointer and zooms by the rate', () => {
    const next = advance({ c: 0.5, s: 100 }, { targetY: 0.9, rate: Math.log(2), dt: 1 }, 0.5)
    expect(next.c).toBeCloseTo(0.7)
    expect(next.s).toBeCloseTo(200)
    expect(advance({ c: 0.99, s: 100 }, { targetY: 5, rate: 0, dt: 1 }).c).toBe(1)
  })

  it('makes whitespace visible on labels', () => {
    expect(tokenLabel(' the')).toBe('·the')
    expect(tokenLabel('\n')).toBe('↵')
  })
})

describe('pointer pace', () => {
  const W = 1000, cross = 200 // hold band: 184 .. 344
  it('holds just right of the line, backs up left of it, speeds up to the right', () => {
    expect(throttle(250, cross, W)).toBe(0)
    expect(throttle(100, cross, W)).toBeLessThan(0)
    expect(throttle(1000, cross, W)).toBeCloseTo(1)
    // gentle at first: halfway through the forward range is well under half speed
    expect(throttle((344 + 1000) / 2, cross, W)).toBeLessThan(0.4)
  })
})
