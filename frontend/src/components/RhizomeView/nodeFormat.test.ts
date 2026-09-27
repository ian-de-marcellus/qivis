import { describe, expect, it } from 'vitest'
import { textTokenCount } from './nodeFormat.ts'

const toks = (...ts: string[]) => ts.map((token) => ({ token }))

describe('textTokenCount', () => {
  it('stops at the saved text: the handover after it shows as one mark', () => {
    expect(textTokenCount(toks(' What', '?', ' Why', '?', '\n\n', 'Ian', ':'), 'What? Why?')).toBe(4)
  })

  it('leaves out an end-of-turn token beyond the text', () => {
    expect(textTokenCount(toks('Hi', '!', '<|eot_id|>'), 'Hi!')).toBe(2)
  })

  it('shows everything when the tokens are the text', () => {
    expect(textTokenCount(toks(' time', ',', ' there'), ' time, there')).toBe(3)
  })
})
