import { describe, expect, it } from 'vitest'
import type { Probe } from '../../api/types.ts'
import { groupByAnswer, shareRange } from './probeGroups.ts'

const probe = (answers: string[] | null): Probe => ({
  probe_id: 'p', node_id: 'n', provider: 'llamacpp', model: 'm', created_at: '',
  prompt_text: '', sampling_params: null,
  samples: (answers ?? ['a', 'b']).map((a) => ({ content: a, finish_reason: 'stop', logprobs: null })),
  judge: answers ? { model: 'j', answers, messages: [] } : null,
})

describe('groupByAnswer', () => {
  it('groups by answer, most common first, "no answer" last', () => {
    const groups = groupByAnswer(probe(['cats', 'no answer', 'dogs', 'cats', 'no answer', 'no answer']))
    expect(groups.map((g) => [g.answer, g.indices])).toEqual([
      ['cats', [0, 3]], ['dogs', [2]], ['no answer', [1, 4, 5]],
    ])
  })

  it('keeps unjudged samples together', () => {
    expect(groupByAnswer(probe(null))).toEqual([{ answer: '', indices: [0, 1] }])
  })
})

describe('shareRange', () => {
  it('is wide for few draws and narrows with more', () => {
    const [lo20, hi20] = shareRange(6, 20)
    expect(lo20).toBeCloseTo(0.145, 2)
    expect(hi20).toBeCloseTo(0.519, 2)
    const [lo200, hi200] = shareRange(60, 200)
    expect(hi200 - lo200).toBeLessThan((hi20 - lo20) / 2.5)
  })

  it('stays within 0 and 1 at the edges', () => {
    expect(shareRange(0, 20)[0]).toBe(0)
    expect(shareRange(20, 20)[1]).toBe(1)
  })
})
