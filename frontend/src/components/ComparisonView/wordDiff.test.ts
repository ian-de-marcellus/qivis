import { describe, expect, it } from 'vitest'
import { computeWordDiff } from './wordDiff.ts'

const text = (segments: ReturnType<typeof computeWordDiff>, type: string) =>
  segments.filter((s) => s.type === type).map((s) => s.text.trim()).join(' ')

describe('computeWordDiff', () => {
  it('marks words only in the other text as added and only in the base as removed', () => {
    const diff = computeWordDiff('the cat sat', 'the dog sat down')
    expect(text(diff, 'removed')).toBe('cat')
    expect(text(diff, 'added')).toBe('dog down')
    expect(text(diff, 'common')).toBe('the sat')
  })

  it('reports identical texts as all common', () => {
    expect(computeWordDiff('same words', 'same words').every((s) => s.type === 'common')).toBe(true)
  })
})
