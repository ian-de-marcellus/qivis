/** Grouping a probe's samples by the answer the judge gave each. */

import type { Probe } from '../../api/types.ts'

export interface Group {
  answer: string
  indices: number[]
}

/** Samples by answer, most common first ("no answer" last); one group if not judged. */
export function groupByAnswer(probe: Probe): Group[] {
  const answers = probe.judge?.answers
  if (!answers) return [{ answer: '', indices: probe.samples.map((_, i) => i) }]
  const groups = new Map<string, number[]>()
  answers.forEach((a, i) => groups.set(a, [...(groups.get(a) ?? []), i]))
  return [...groups.entries()]
    .map(([answer, indices]) => ({ answer, indices }))
    .sort((x, y) =>
      Number(x.answer === 'no answer') - Number(y.answer === 'no answer')
      || y.indices.length - x.indices.length)
}
