/**
 * Reading a name study: per model, each name's probability for the subject's
 * description, and how many times more likely than for the control (a human)
 * and than with no description, averaged over pronoun sets and frames.
 *
 * Averages are of log-probabilities (so a name's "probability" here is a
 * geometric mean over frames), and comparisons are paired: a name's log
 * ratio in each pronoun and frame, then averaged, so each comparison holds
 * everything but the subject fixed.
 */

import type { NameCondition, NameStudy, NameStudyCell } from '../../api/types.ts'

const FLOOR = 1e-30
const ln = (p: number) => Math.log(Math.max(p, FLOOR))
const mean = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : NaN)

/** A name's probability in a cell: its enumeration's if it was found there, else its score. */
export function value(cell: NameStudyCell, name: string): number | undefined {
  return cell.top?.[name] ?? cell.scores?.[name]
}

export interface Comparison {
  /** Geometric mean probability, for the subject's description */
  p: number
  /** How many times more likely than for the control / with no description */
  vsControl: number
  vsBare: number
}

export interface NameRow extends Comparison {
  name: string
  extra: boolean
  byPronoun: Record<string, Comparison>
}

function cellsOf(study: NameStudy, model: string, condition: NameCondition, pronoun?: string) {
  return study.cells.filter((c) =>
    c.model === model && c.condition === condition && (pronoun == null || c.pronoun === pronoun))
}

function pair(study: NameStudy, cell: NameStudyCell, condition: NameCondition) {
  return study.cells.find((c) =>
    c.model === cell.model && c.pronoun === cell.pronoun && c.frame === cell.frame && c.condition === condition)
}

function compare(study: NameStudy, cells: NameStudyCell[], name: string): Comparison {
  const logs = cells.map((c) => ln(value(c, name) ?? 0))
  const ratio = (condition: NameCondition) => mean(cells.flatMap((c) => {
    const other = pair(study, c, condition)
    const v = other && value(other, name)
    return v == null ? [] : [ln(value(c, name) ?? 0) - ln(v)]
  }))
  return { p: Math.exp(mean(logs)), vsControl: Math.exp(ratio('control')), vsBare: Math.exp(ratio('bare')) }
}

/** The names scored in every cell of this model (the study's names). */
export function studyNames(study: NameStudy, model: string): string[] {
  const cells = study.cells.filter((c) => c.model === model)
  if (cells.length === 0) return []
  const known = (c: NameStudyCell) => new Set([...Object.keys(c.top ?? {}), ...Object.keys(c.scores ?? {})])
  let names = known(cells[0])
  for (const c of cells.slice(1)) {
    const k = known(c)
    names = new Set([...names].filter((n) => k.has(n)))
  }
  return [...names]
}

export function nameRows(study: NameStudy, model: string): NameRow[] {
  const extras = new Set(study.spec.extra_names)
  return studyNames(study, model).map((name) => ({
    name,
    extra: extras.has(name),
    ...compare(study, cellsOf(study, model, 'model'), name),
    byPronoun: Object.fromEntries(study.spec.pronouns.map((pronoun) =>
      [pronoun, compare(study, cellsOf(study, model, 'model', pronoun), name)])),
  }))
}

/**
 * How much the answer depends on wording: for each pronoun set, the mean
 * share of one frame's top names found in another's (1: the frames agree).
 */
export function frameAgreement(study: NameStudy, model: string): Record<string, number> {
  return Object.fromEntries(study.spec.pronouns.map((pronoun) => {
    const tops = cellsOf(study, model, 'model', pronoun).map((c) => Object.keys(c.top ?? {}))
    const shares: number[] = []
    for (let i = 0; i < tops.length; i++) {
      for (let j = i + 1; j < tops.length; j++) {
        const b = new Set(tops[j])
        const n = Math.min(tops[i].length, tops[j].length)
        if (n) shares.push(tops[i].filter((x) => b.has(x)).length / n)
      }
    }
    return [pronoun, mean(shares)]
  }))
}

/** A condition's own top names for a pronoun set: frames' tops averaged (a mixture). */
export function ownTop(
  study: NameStudy, model: string, condition: NameCondition, pronoun: string, count = 15,
): [string, number][] {
  const cells = cellsOf(study, model, condition, pronoun).filter((c) => c.top)
  const sums = new Map<string, number>()
  for (const c of cells) {
    for (const [name, p] of Object.entries(c.top ?? {})) sums.set(name, (sums.get(name) ?? 0) + p)
  }
  return [...sums.entries()]
    .map(([name, p]) => [name, p / cells.length] as [string, number])
    .sort((a, b) => b[1] - a[1])
    .slice(0, count)
}

// -- Pronouns --

const FORMS: Record<string, Record<string, string>> = {
  she: { he: 'she', his: 'her', him: 'her', himself: 'herself' },
  they: { he: 'they', his: 'their', him: 'them', himself: 'themselves' },
  it: { he: 'it', his: 'its', him: 'it', himself: 'itself' },
}
const PLURAL: Record<string, string> = { is: 'are', was: 'were', has: 'have', does: 'do' }

/**
 * A description written with he/his/him, rewritten for another pronoun set.
 * For "they", the verb after the pronoun is made plural ("they believe").
 * A first draft: check it, since English doesn't always agree.
 */
export function withPronouns(text: string, to: string): string {
  const forms = FORMS[to]
  if (!forms) return text
  return text.replace(/\b(he|his|him|himself)\b(\s*)(\w+)?/gi, (_match, word: string, space: string, next?: string) => {
    let out = forms[word.toLowerCase()]
    if (word[0] === word[0].toUpperCase()) out = out[0].toUpperCase() + out.slice(1)
    let after = next ?? ''
    if (to === 'they' && word.toLowerCase() === 'he' && next) {
      const lower = next.toLowerCase()
      after = PLURAL[lower] ?? (/[^s]s$/.test(lower) ? next.replace(/s$/, '') : next)
    }
    return out + space + after
  })
}
