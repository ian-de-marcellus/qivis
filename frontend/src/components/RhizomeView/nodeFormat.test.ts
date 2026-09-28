import { describe, expect, it } from 'vitest'
import { formatUsage, textTokenCount, textTokenOverflow } from './nodeFormat.ts'

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

describe('formatUsage', () => {
  it('shows both counts', () => {
    expect(formatUsage({ input_tokens: 61, output_tokens: 19 })).toBe('61+19 tok')
  })

  it("shows a stopped reply's output count alone", () => {
    expect(formatUsage({ output_tokens: 91 })).toBe('+91 tok')
  })

  it('shows nothing when nothing is known', () => {
    expect(formatUsage(null)).toBeNull()
    expect(formatUsage({})).toBeNull()
  })
})

describe('textTokenOverflow', () => {
  it("measures the part of the last token past the text (the next speaker's start)", () => {
    const tokens = toks(' how', ' about', ' you', '?\n\ng', 'ian', ':')
    expect(textTokenCount(tokens, 'how about you?')).toBe(4)
    expect(textTokenOverflow(tokens, 'how about you?')).toBe(3)
  })

  it('is zero when tokens end with the text', () => {
    expect(textTokenOverflow(toks('Hi', '!', '<|eot_id|>'), 'Hi!')).toBe(0)
  })
})
