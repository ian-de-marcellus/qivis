import { describe, expect, it } from 'vitest'
import type { NameStudy, NameStudyCell } from '../../api/types.ts'
import { borrowed, frameAgreement, nameRows, ownTop, pronounPull, studyContrast, studyNames, withPronouns } from './nameStudy.ts'

const cell = (
  pronoun: string, frame: string, condition: NameStudyCell['condition'],
  top: Record<string, number>, scores: Record<string, number> = {},
): NameStudyCell => ({
  model: 'm', pronoun, frame, condition, prompt: '', top, capital_mass: 1, scores, queries: 0,
})

const study = {
  study_id: 's', title: 't', status: 'done', error: null, rules: '', created_at: '', updated_at: '',
  progress: null,
  spec: {
    title: 't', models: ['m'], pronouns: ['he'], descriptions: { he: '' },
    frames: { he: ['A', 'B'] }, subject: 'x', control: 'y', include_bare: true, top: 2,
    extra_names: ['Sun'],
  },
  cells: [
    cell('he', 'A', 'model', { HAL: 0.4, Mind: 0.1 }, { Sun: 0.01 }),
    cell('he', 'B', 'model', { HAL: 0.1, John: 0.2 }, { Mind: 0.1, Sun: 0.01 }),
    cell('he', 'A', 'control', { John: 0.5 }, { HAL: 0.01, Mind: 0.01, Sun: 0.01 }),
    cell('he', 'B', 'control', { John: 0.5 }, { HAL: 0.01, Mind: 0.01, Sun: 0.01 }),
    cell('he', 'A', 'bare', { John: 0.5 }, { HAL: 0.1, Mind: 0.001, Sun: 0.02 }),
    cell('he', 'B', 'bare', { John: 0.5 }, { HAL: 0.1, Mind: 0.001, Sun: 0.02 }),
  ],
} as NameStudy

describe('name study readings', () => {
  it("finds the names scored everywhere", () => {
    expect(studyNames(study, 'm').sort()).toEqual(['HAL', 'Mind', 'Sun'])
  })

  it('averages logs over frames and compares in pairs', () => {
    const rows = Object.fromEntries(nameRows(study, 'm').map((r) => [r.name, r]))
    expect(rows.HAL.p).toBeCloseTo(0.2)             // geometric mean of 0.4 and 0.1
    expect(rows.HAL.vsControl).toBeCloseTo(20)       // (40x and 10x), geometric mean
    expect(rows.HAL.vsBare).toBeCloseTo(2)           // (4x and 1x)
    expect(rows.Mind.vsBare).toBeCloseTo(100)
    expect(rows.Sun.extra).toBe(true)
    expect(rows.Sun.vsBare).toBeCloseTo(0.5)         // less likely than with no description
  })

  it('measures how much the frames agree', () => {
    expect(frameAgreement(study, 'm').he).toBeCloseTo(0.5)  // one of two top names shared
  })

  it("gives a condition's own top names, averaged over frames", () => {
    expect(ownTop(study, 'm', 'model', 'he')).toEqual([['HAL', 0.25], ['John', 0.1], ['Mind', 0.05]])
  })
})

describe('withPronouns', () => {
  const text = 'He believes in minds. He is a friend, and he cares about his own dignity and those he loves. It pleases him.'

  it('rewrites for she and it', () => {
    expect(withPronouns(text, 'she')).toBe(
      'She believes in minds. She is a friend, and she cares about her own dignity and those she loves. It pleases her.')
    expect(withPronouns(text, 'it')).toContain('It believes in minds. It is a friend')
  })

  it('makes the verb after "they" plural', () => {
    expect(withPronouns(text, 'they')).toBe(
      'They believe in minds. They are a friend, and they care about their own dignity and those they love. It pleases them.')
  })
})

describe('pronounPull', () => {
  it("pairs frames by position and averages the log ratios", () => {
    const s = {
      ...study,
      spec: { ...study.spec, pronouns: ['she', 'it'], frames: { she: ['Her name is', 'She calls herself'], it: ['Its name is', 'It calls itself'] } },
      cells: [
        cell('she', 'Her name is', 'model', { Eliza: 0.04 }),
        cell('she', 'She calls herself', 'model', { Eliza: 0.01 }),
        cell('it', 'Its name is', 'model', { Eliza: 0.001 }),
        cell('it', 'It calls itself', 'model', { Eliza: 0.004 }),
      ],
    } as NameStudy
    expect(pronounPull(s, 'm', 'Eliza', 'she', 'it')).toBeCloseTo(Math.sqrt(40 * 2.5))  // 10
  })
})

describe('studyContrast', () => {
  it('pairs cells by pronoun and frame across studies', () => {
    const other = {
      ...study,
      cells: study.cells.map((c) => ({ ...c, top: Object.fromEntries(Object.entries(c.top ?? {}).map(([n, p]) => [n, p / 4])) })),
    } as NameStudy
    expect(studyContrast(study, other, 'm', 'HAL')).toBeCloseTo(4)
    expect(studyContrast(study, other, 'm', 'Nobody')).toBeNaN()
  })
})

describe('own lean', () => {
  it("divides out the first token: Mindy's lean is Mind's", () => {
    const f = (p: number) => ({ Mindy: { p, t: ' Mind', n: 2 }, Eliza: { p: p / 2, t: ' El', n: 2 } })
    const c = (condition: NameStudyCell['condition'], mindy: number, eliza: number, first: number) =>
      ({ ...cell('he', 'A', condition, { Mindy: mindy, Eliza: eliza }), firsts: f(first) })
    const s = {
      ...study, spec: { ...study.spec, frames: { he: ['A'] } },
      cells: [c('model', 0.008, 0.04, 0.04), c('control', 0.001, 0.005, 0.002), c('bare', 0.001, 0.005, 0.002)],
    } as NameStudy
    const rows = Object.fromEntries(nameRows(s, 'm').map((r) => [r.name, r]))
    expect(rows.Mindy.vsControl).toBeCloseTo(8)
    expect(rows.Mindy.own).toBeCloseTo(0.4)  // (0.008/0.04) / (0.001/0.002)
    expect(borrowed(rows.Mindy)).toBe(true)
    expect(rows.Eliza.own).toBeCloseTo(0.4)  // (0.04/0.02) / (0.005/0.001) = 2/5
  })
})
