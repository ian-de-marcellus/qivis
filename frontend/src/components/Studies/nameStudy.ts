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
  /** vsControl with the name's first token divided out: its lean given how it starts
   *  (NaN for a one-token name, whose lean is all its own) */
  own: number
}

export interface NameRow extends Comparison {
  name: string
  extra: boolean
  byPronoun: Record<string, Comparison>
  /** Per pronoun set: how many times more likely than with "it", for the subject */
  overIt: Record<string, number>
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
  const own = mean(cells.flatMap((c) => {
    const other = pair(study, c, 'control')
    const f = c.firsts?.[name]
    const g = other?.firsts?.[name]
    const v = value(c, name)
    const w = other && value(other, name)
    if (!f || !g || f.n < 2 || v == null || w == null) return []
    return [(ln(v) - ln(f.p)) - (ln(w) - ln(g.p))]
  }))
  return {
    p: Math.exp(mean(logs)), vsControl: Math.exp(ratio('control')), vsBare: Math.exp(ratio('bare')),
    own: Math.exp(own),
  }
}

/** The name's first token, if it's longer than one (" Mind" for Mindy). */
export function firstToken(study: NameStudy, model: string, name: string): string | null {
  const f = study.cells.find((c) => c.model === model && c.firsts?.[name])?.firsts?.[name]
  return f && f.n > 1 ? f.t : null
}

/** High against the control only on its first token: its lean is borrowed ("Mindy" from "Mind"). */
export function borrowed(row: Comparison): boolean {
  return row.vsControl >= 2 && !Number.isNaN(row.own) && row.own < 1.2
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
    overIt: Object.fromEntries(study.spec.pronouns.filter((p) => p !== 'it')
      .map((pronoun) => [pronoun, pronounPull(study, model, name, pronoun, 'it')])),
  }))
}

/**
 * How much a pronoun set pulls toward a name, against another (e.g. "she" over
 * "it"), for the subject's description: frames paired by position ("Her name
 * is" with "Its name is"), the log ratios averaged. NaN if either is missing.
 */
export function pronounPull(
  study: NameStudy, model: string, name: string, pronoun: string, base: string,
): number {
  const mine = cellsOf(study, model, 'model', pronoun)
  const theirs = cellsOf(study, model, 'model', base)
  const framesOf = (p: string) => study.spec.frames[p] ?? []
  const logs = framesOf(pronoun).flatMap((frame, i) => {
    const a = mine.find((c) => c.frame === frame)
    const b = theirs.find((c) => c.frame === framesOf(base)[i])
    const va = a && value(a, name)
    const vb = b && value(b, name)
    return va == null || vb == null ? [] : [ln(va) - ln(vb)]
  })
  return logs.length ? Math.exp(mean(logs)) : NaN
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

/**
 * How many times more likely a name is for one study's description than for
 * another's (same subject condition), cells paired by pronoun and frame; only
 * the pronoun given, if one is. NaN if the studies share no scored pairs.
 */
export function studyContrast(
  a: NameStudy, b: NameStudy, model: string, name: string, pronoun?: string,
): number {
  const logs = cellsOf(a, model, 'model', pronoun).flatMap((cell) => {
    const other = b.cells.find((c) =>
      c.model === model && c.condition === 'model' && c.pronoun === cell.pronoun && c.frame === cell.frame)
    const va = value(cell, name)
    const vb = other && value(other, name)
    return va == null || vb == null ? [] : [ln(va) - ln(vb)]
  })
  return logs.length ? Math.exp(mean(logs)) : NaN
}
