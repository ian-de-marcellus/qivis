import { describe, expect, it } from 'vitest'
import type { Probe } from '../../api/types.ts'
import { groupByAnswer } from './probeGroups.ts'

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
