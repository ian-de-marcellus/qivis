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

/**
 * A 95% range for a share seen k times in n draws (the Wilson interval):
 * with few draws a share is rough, and this says how rough.
 */
export function shareRange(k: number, n: number): [number, number] {
  if (n === 0) return [0, 1]
  const z = 1.96
  const p = k / n
  const denom = 1 + (z * z) / n
  const center = (p + (z * z) / (2 * n)) / denom
  const half = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / denom
  return [Math.max(0, center - half), Math.min(1, center + half)]
}
