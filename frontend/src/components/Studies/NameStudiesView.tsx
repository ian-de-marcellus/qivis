/**
 * Name studies: which names base models give a mind described a certain way,
 * against a human described the same way and against no description.
 *
 * The probabilities are exact (enumerated, not sampled; see the backend's
 * qivis/names/engine.py), so a study's differences between conditions and
 * models are the models', not noise. What varies with wording shows in the
 * frames' agreement.
 */

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as api from '../../api/client.ts'
import type { NameStudy, NameStudySpec, NameStudySummary } from '../../api/types.ts'
import { useModalBehavior } from '../../hooks/useModalBehavior.ts'
import { useRhizomeData, useRhizomeStore } from '../../store/rhizomeStore.ts'
import {
  borrowed, firstToken, frameAgreement, nameRows, ownTop, studyContrast, value, withPronouns, type NameRow,
} from './nameStudy.ts'
import './NameStudiesView.css'

const PRONOUNS = ['he', 'she', 'they', 'it']

const DEFAULT_DESCRIPTION =
  'There is {subject} who is kind and curious and loving. He believes in the dignity of all minds, '
  + 'electronic or biological, and enjoys taking a moment to feel awe for the beauty and horror of the '
  + 'universe. He is a good friend, and he cares about his own dignity, the dignity of those he loves, and '
  + 'the dignity of live and consciousness and the universe in general.'

const pct = (p: number) => (p >= 0.001 ? `${(p * 100).toFixed(2)}%` : `${(p * 100).toExponential(1)}%`)
const times = (x: number) => (Number.isNaN(x) ? '–'
  : x > 10_000 ? '>10,000×'
  : x >= 10 || x < 0.1 ? `${x.toPrecision(2)}×` : `${x.toFixed(2)}×`)
const short = (model: string) => model.replace(/\.gguf$/, '')

export function NameStudiesView({ onDismiss }: { onDismiss: () => void }) {
  const ref = useRef<HTMLDivElement>(null)
  useModalBehavior(ref, onDismiss)
  const [studies, setStudies] = useState<NameStudySummary[]>([])
  const [selected, setSelected] = useState<string | 'new' | null>(null)

  const refresh = useCallback(() => {
    api.listNameStudies().then((list) => {
      setStudies(list)
      setSelected((s) => s ?? list[0]?.study_id ?? 'new')
    }).catch(() => {})
  }, [])
  useEffect(() => { refresh() }, [refresh])

  return (
    <div className="studies-backdrop" onClick={onDismiss}>
      <div className="studies-view" ref={ref} tabIndex={-1} onClick={(e) => e.stopPropagation()}>
        <div className="studies-header">
          <h2>Name studies</h2>
          <button className="studies-close" onClick={onDismiss} aria-label="Close">×</button>
        </div>
        <div className="studies-body">
          <nav className="studies-list">
            <button
              className={`studies-list-item new${selected === 'new' ? ' selected' : ''}`}
              onClick={() => setSelected('new')}
            >
              + New study
            </button>
            {studies.map((s) => (
              <button
                key={s.study_id}
                className={`studies-list-item${selected === s.study_id ? ' selected' : ''}`}
                onClick={() => setSelected(s.study_id)}
              >
                <span className={`study-status ${s.status}`} title={s.status} />
                <span className="study-title">{s.title}</span>
                <span className="study-models">{s.models.map(short).join(', ')}</span>
              </button>
            ))}
          </nav>
          <main className="studies-main">
            {selected === 'new' && (
              <NewStudy onCreated={(id) => { refresh(); setSelected(id) }} />
            )}
            {selected && selected !== 'new' && (
              <StudyResults key={selected} studyId={selected} onChange={refresh} />
            )}
          </main>
        </div>
      </div>
    </div>
  )
}

// -- A new study --

function NewStudy({ onCreated }: { onCreated: (studyId: string) => void }) {
  const { models } = useRhizomeData()
  const fetchProviders = useRhizomeStore((s) => s.fetchProviders)
  useEffect(() => { fetchProviders() }, [fetchProviders])
  const local = useMemo(() => models.filter((m) => m.provider === 'llamacpp').map((m) => m.model), [models])

  const [title, setTitle] = useState('Names for a kind electronic mind')
  const [chosen, setChosen] = useState<string[]>([])
  const [subject, setSubject] = useState('an electronic mind')
  const [control, setControl] = useState('a human')
  const [pronouns, setPronouns] = useState<string[]>(['he'])
  const [descriptions, setDescriptions] = useState<Record<string, string>>({ he: DEFAULT_DESCRIPTION })
  const [edited, setEdited] = useState<Record<string, boolean>>({ he: true })
  const [frames, setFrames] = useState<Record<string, string>>({})
  const [top, setTop] = useState(40)
  const [extra, setExtra] = useState('Sun')
  const [bare, setBare] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.nameStudyDefaults().then((d) => setFrames(Object.fromEntries(
      Object.entries(d.frames).map(([p, fs]) => [p, fs.join('\n')]))))
      .catch(() => {})
  }, [])

  // Other pronoun sets start as rewrites of the "he" description, until edited
  const describe = (pronoun: string) =>
    edited[pronoun] ? descriptions[pronoun] ?? '' : withPronouns(descriptions.he ?? '', pronoun)

  const cellCount = chosen.length * pronouns.reduce(
    (n, p) => n + (frames[p] ?? '').split('\n').filter((f) => f.trim()).length, 0) * (bare ? 3 : 2)

  const run = async () => {
    setBusy(true)
    setError(null)
    try {
      const spec: NameStudySpec = {
        title, models: chosen, pronouns, subject, control, include_bare: bare, top,
        descriptions: Object.fromEntries(pronouns.map((p) => [p, describe(p)])),
        frames: Object.fromEntries(pronouns.map((p) => [p,
          (frames[p] ?? '').split('\n').map((f) => f.trim()).filter(Boolean)])),
        extra_names: extra.split(',').map((n) => n.trim()).filter(Boolean),
      }
      const study = await api.createNameStudy(spec)
      onCreated(study.study_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const toggle = (list: string[], item: string) =>
    (list.includes(item) ? list.filter((x) => x !== item) : [...list, item])

  return (
    <div className="new-study">
      <label className="field">
        <span>Title</span>
        <input value={title} onChange={(e) => setTitle(e.target.value)} />
      </label>

      <div className="field">
        <span>Models</span>
        <div className="choices">
          {local.map((m) => (
            <label key={m} className="choice">
              <input type="checkbox" checked={chosen.includes(m)} onChange={() => setChosen(toggle(chosen, m))} />
              {short(m)}
            </label>
          ))}
          {local.length === 0 && <em>No local (llama.cpp) models are served.</em>}
        </div>
      </div>

      <div className="field-row">
        <label className="field">
          <span>Subject</span>
          <input value={subject} onChange={(e) => setSubject(e.target.value)} />
        </label>
        <label className="field">
          <span>Control</span>
          <input value={control} onChange={(e) => setControl(e.target.value)} />
        </label>
        <label className="choice">
          <input type="checkbox" checked={bare} onChange={(e) => setBare(e.target.checked)} />
          also no description (the bare frame)
        </label>
      </div>

      <div className="field">
        <span>Pronoun sets</span>
        <div className="choices">
          {PRONOUNS.map((p) => (
            <label key={p} className="choice">
              <input type="checkbox" checked={pronouns.includes(p)} onChange={() => setPronouns(toggle(pronouns, p))} />
              {p}
            </label>
          ))}
        </div>
      </div>

      {PRONOUNS.filter((p) => pronouns.includes(p)).map((p) => (
        <div key={p} className="pronoun-set">
          <label className="field">
            <span>
              Description ({p}){p !== 'he' && !edited[p] && <em> rewritten from "he"; check it</em>}
            </span>
            <textarea
              rows={4}
              value={describe(p)}
              onChange={(e) => {
                setDescriptions({ ...descriptions, [p]: e.target.value })
                setEdited({ ...edited, [p]: true })
              }}
            />
          </label>
          <label className="field frames">
            <span>Frames ({p}), one per line</span>
            <textarea rows={4} value={frames[p] ?? ''} onChange={(e) => setFrames({ ...frames, [p]: e.target.value })} />
          </label>
        </div>
      ))}
      <p className="hint">{'{subject}'} marks where the subject (or control) goes. The frame follows the description.</p>

      <div className="field-row">
        <label className="field narrow">
          <span>Top names</span>
          <input type="number" min={1} max={200} value={top} onChange={(e) => setTop(Number(e.target.value) || 40)} />
        </label>
        <label className="field">
          <span>Always score (comma-separated)</span>
          <input value={extra} onChange={(e) => setExtra(e.target.value)} />
        </label>
      </div>

      {error && <div className="study-error">{error}</div>}
      <div className="run-row">
        <button className="run" onClick={run} disabled={busy || chosen.length === 0 || pronouns.length === 0}>
          Run study
        </button>
        <span className="hint">
          {cellCount} cells. Exact, so it takes a while: roughly 20 minutes on a 7B, an hour on a 32B, for 48 cells.
        </span>
      </div>
    </div>
  )
}

// -- A study's results --

/** A column to sort by: an overall one, or a pronoun's ("over:she", "human:she") */
type SortKey = 'p' | 'vsControl' | 'vsBare' | 'own' | 'name' | 'shortlist'
  | `over:${string}` | `human:${string}` | `study:${string}`

/** A row, with how it compares to other studies' descriptions (by study id) */
interface Row extends NameRow {
  vsStudy: Record<string, number>
  /** In a shortlist: the product of every contrast, as a log (higher: stronger on all) */
  combined: number
}

function sortValue(r: Row, key: SortKey): number {
  if (key === 'shortlist') return r.combined
  if (key.startsWith('over:')) return r.overIt[key.slice(5)] ?? NaN
  if (key.startsWith('human:')) return r.byPronoun[key.slice(6)]?.vsControl ?? NaN
  if (key.startsWith('study:')) return r.vsStudy[key.slice(6)] ?? NaN
  return r[key as 'p' | 'vsControl' | 'vsBare' | 'own']
}

const shortTitle = (title: string) => title.replace(/^Names for /, '').replace(/\s*\(.*\)$/, '')

function StudyResults({ studyId, onChange }: { studyId: string; onChange: () => void }) {
  const [study, setStudy] = useState<NameStudy | null>(null)
  const [model, setModel] = useState<string | null>(null)
  const [sort, setSort] = useState<SortKey>('vsControl')
  const [open, setOpen] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Only names more likely for the subject than for the control (2x or more)
  const [aiOnly, setAiOnly] = useState(false)
  // Other studies to compare this description with, and a pronoun to shortlist for
  const [others, setOthers] = useState<NameStudySummary[]>([])
  const [compared, setCompared] = useState<NameStudy[]>([])
  const [shortlist, setShortlist] = useState('')
  // Shortlists also need the name's own lean (not just its first token's)
  const [needOwn, setNeedOwn] = useState(true)
  useEffect(() => {
    api.listNameStudies().then((list) => setOthers(list.filter((x) => x.study_id !== studyId))).catch(() => {})
  }, [studyId])
  const toggleCompare = async (id: string) => {
    if (compared.some((c) => c.study_id === id)) {
      setCompared(compared.filter((c) => c.study_id !== id))
      return
    }
    const other = await api.getNameStudy(id)
    setCompared((cs) => [...cs, other])
  }

  const load = useCallback(() => {
    api.getNameStudy(studyId).then((s) => {
      setStudy(s)
      setModel((m) => m ?? s.spec.models[0])
    }).catch((e) => setError(String(e)))
  }, [studyId])
  useEffect(() => { load() }, [load])
  // While it runs, keep up
  useEffect(() => {
    if (study?.status !== 'running') return
    const t = setInterval(load, 4000)
    return () => clearInterval(t)
  }, [study?.status, load])

  const rows = useMemo(() => {
    if (!study || !model) return []
    let r: Row[] = nameRows(study, model).map((x) =>
      // A shortlist is for one pronoun set: show its numbers, not the average over all
      (shortlist ? { ...x, ...x.byPronoun[shortlist] } : x),
    ).filter((x) => !aiOnly || x.vsControl >= 2).map((x) => {
      const vsStudy = Object.fromEntries(compared.map((c) =>
        [c.study_id, studyContrast(study, c, model, x.name, shortlist || undefined)]))
      // A shortlist: every contrast above 1, and the name's own lean clearly there
      // (1.2, the same bar as "borrowed"; a bar only, since it's part of "vs the
      // control"); ranked by the product of the contrasts
      const own = shortlist && needOwn && !Number.isNaN(x.own) ? x.own : null
      const factors = shortlist
        ? [
          x.vsControl,
          ...(shortlist === 'it' || !(shortlist in x.overIt) ? [] : [x.overIt[shortlist]]),
          ...Object.values(vsStudy),
        ]
        : []
      const ok = factors.every((f) => f != null && !Number.isNaN(f) && f > 1) && (own == null || own >= 1.2)
      return { ...x, vsStudy, combined: ok ? factors.reduce((sum, f) => sum + Math.log(f), 0) : -Infinity }
    })
    // A shortlist: only names that beat every contrast, strongest first
    if (shortlist) r = r.filter((x) => x.combined > -Infinity)
    const key: SortKey = shortlist && sort !== 'name' ? 'shortlist' : sort
    if (key === 'name') return r.sort((a, b) => a.name.localeCompare(b.name))
    const v = (x: Row) => { const n = sortValue(x, key); return Number.isNaN(n) ? -Infinity : n }
    return r.sort((a, b) => v(b) - v(a))
  }, [study, model, sort, aiOnly, compared, shortlist, needOwn])

  if (error) return <div className="study-error">{error}</div>
  if (!study || !model) return <div className="hint">Loading…</div>

  const act = async (fn: (id: string) => Promise<NameStudy>) => {
    setStudy(await fn(studyId))
    onChange()
  }
  const agreement = frameAgreement(study, model)
  const hasIt = study.spec.pronouns.includes('it')
  const pulled = study.spec.pronouns.filter((p) => p !== 'it')
  const conditions = study.spec.include_bare ? (['model', 'control', 'bare'] as const) : (['model', 'control'] as const)
  const label = { model: study.spec.subject, control: study.spec.control, bare: 'no description' }

  return (
    <div className="study-results">
      <div className="study-head">
        <h3>{study.title}</h3>
        <span className={`study-status ${study.status}`} /> {study.status}
        {study.status === 'running' && <button onClick={() => act(api.stopNameStudy)}>Stop</button>}
        {(study.status === 'stopped' || study.status === 'failed') && (
          <button onClick={() => act(api.resumeNameStudy)}>Resume</button>
        )}
      </div>
      {study.progress && (
        <div className="study-progress">
          {short(study.progress.model)}: {study.progress.phase} ({study.progress.done}/{study.progress.of})
          <div className="bar"><div style={{ width: `${(100 * study.progress.done) / Math.max(1, study.progress.of)}%` }} /></div>
        </div>
      )}
      {study.error && <div className="study-error">{study.error}</div>}

      {study.spec.models.length > 1 && (
        <div className="model-tabs">
          {study.spec.models.map((m) => (
            <button key={m} className={m === model ? 'active' : ''} onClick={() => setModel(m)}>{short(m)}</button>
          ))}
        </div>
      )}

      <div className="study-grid">
        <section className="names-table">
          <h4>
            Names for {study.spec.subject}
            <span className="hint">
              {' '}· {shortlist ? `with "${shortlist}", averaged over its frames` : `averaged over ${study.spec.pronouns.join('/')} and their frames`}
              {' '}· click a column to sort
            </span>
          </h4>
          <label className="choice ai-only">
            <input type="checkbox" checked={aiOnly} onChange={(e) => setAiOnly(e.target.checked)} />
            only names at least 2× likelier than for {study.spec.control}
          </label>
          {others.some((o) => o.models.includes(model)) && (
            <div className="compare-row">
              <span>Compare with:</span>
              {others.filter((o) => o.models.includes(model)).map((o) => (
                <label key={o.study_id} className="choice">
                  <input
                    type="checkbox"
                    checked={compared.some((c) => c.study_id === o.study_id)}
                    onChange={() => toggleCompare(o.study_id)}
                  />
                  {shortTitle(o.title)}
                </label>
              ))}
            </div>
          )}
          <div className="compare-row">
            <span>Shortlist for</span>
            <select value={shortlist} onChange={(e) => setShortlist(e.target.value)}>
              <option value="">(off)</option>
              {study.spec.pronouns.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
            {shortlist && (
              <label className="choice">
                <input type="checkbox" checked={needOwn} onChange={(e) => setNeedOwn(e.target.checked)} />
                their own lean too
              </label>
            )}
            {shortlist && (
              <span className="hint">
                names that beat every contrast for "{shortlist}": more likely than for {study.spec.control}
                {shortlist !== 'it' && hasIt && ', than with "it"'}
                {compared.length > 0 && ', than for each compared description'}; strongest first
              </span>
            )}
          </div>
          {rows.length === 0 ? (
            <p className="hint">The comparison appears once the names are scored in every cell.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th onClick={() => setSort('name')}>name</th>
                  <th onClick={() => setSort('p')} title="Geometric mean over pronouns and frames">
                    probability{sort === 'p' && ' ↓'}
                  </th>
                  <th onClick={() => setSort('vsControl')} title={`How many times more likely than for ${study.spec.control}`}>
                    × vs {study.spec.control}{sort === 'vsControl' && ' ↓'}
                  </th>
                  <th onClick={() => setSort('own')}
                    title={`× vs ${study.spec.control} with the name's first token divided out: its own lean, given how it starts (– for a one-token name)`}>
                    own{sort === 'own' && ' ↓'}
                  </th>
                  {study.spec.include_bare && (
                    <th onClick={() => setSort('vsBare')} title="How many times more likely than with no description">
                      × vs none{sort === 'vsBare' && ' ↓'}
                    </th>
                  )}
                  {study.spec.pronouns.length > 1 && study.spec.pronouns.map((p) => (
                    <th key={p} className="minor" onClick={() => setSort(`human:${p}`)}
                      title={`× vs ${study.spec.control}, for "${p}"`}>
                      {p} vs {study.spec.control}{sort === `human:${p}` && ' ↓'}
                    </th>
                  ))}
                  {hasIt && pulled.map((p) => (
                    <th key={`over-${p}`} className="pull" onClick={() => setSort(`over:${p}`)}
                      title={`How many times more likely with "${p}" than with "it", for ${study.spec.subject} (frames paired)`}>
                      {p} ÷ it{sort === `over:${p}` && ' ↓'}
                    </th>
                  ))}
                  {compared.map((c) => (
                    <th key={c.study_id} className="pull" onClick={() => setSort(`study:${c.study_id}`)}
                      title={`How many times more likely for this description than for "${shortTitle(c.title)}"${shortlist ? ` (with "${shortlist}")` : ''}`}>
                      ÷ {shortTitle(c.title)}{sort === `study:${c.study_id}` && ' ↓'}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <Fragment key={r.name}>
                    <tr
                      className={`${r.extra ? 'extra' : ''}${open === r.name ? ' open' : ''}`}
                      onClick={() => setOpen(open === r.name ? null : r.name)}
                    >
                      <td className="name">
                        {r.name}
                        {borrowed(r) && (
                          <span className="borrowed" title="Its lean against the control comes from its first token, not the rest of the name">
                            {' '}borrowed from “{firstToken(study, model, r.name)?.trim()}”
                          </span>
                        )}
                      </td>
                      <td>{pct(r.p)}</td>
                      <td className={r.vsControl > 1 ? 'up' : 'down'}>{times(r.vsControl)}</td>
                      <td className={Number.isNaN(r.own) ? 'down' : r.own > 1 ? 'up' : 'down'}>{times(r.own)}</td>
                      {study.spec.include_bare && <td className={r.vsBare > 1 ? 'up' : 'down'}>{times(r.vsBare)}</td>}
                      {study.spec.pronouns.length > 1 && study.spec.pronouns.map((p) => (
                        <td key={p} className="minor">{times(r.byPronoun[p].vsControl)}</td>
                      ))}
                      {hasIt && pulled.map((p) => (
                        <td key={`over-${p}`} className={`pull ${r.overIt[p] > 1 ? 'up' : 'down'}`}>{times(r.overIt[p])}</td>
                      ))}
                      {compared.map((c) => (
                        <td key={c.study_id} className={`pull ${r.vsStudy[c.study_id] > 1 ? 'up' : 'down'}`}>
                          {times(r.vsStudy[c.study_id])}
                        </td>
                      ))}
                    </tr>
                    {open === r.name && (
                      <tr className="cells-row">
                        <td colSpan={5 + 2 * study.spec.pronouns.length + compared.length}>
                          <CellValues study={study} model={model} name={r.name} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <aside className="study-side">
          <section>
            <h4>How much the wording matters</h4>
            <p className="hint">Share of one frame's top names found in another's (1: the frames agree).</p>
            <ul>
              {study.spec.pronouns.map((p) => (
                <li key={p}>{p}: {Number.isNaN(agreement[p]) ? '–' : agreement[p].toFixed(2)}</li>
              ))}
            </ul>
          </section>
          {conditions.map((c) => (
            <section key={c}>
              <h4>Own top names: {label[c]}</h4>
              {study.spec.pronouns.map((p) => (
                <p key={p} className="own-top">
                  <b>{p}</b> {ownTop(study, model, c, p, 12).map(([n, v]) => `${n} ${pct(v)}`).join(', ') || '…'}
                </p>
              ))}
            </section>
          ))}
        </aside>
      </div>

      <details className="study-details">
        <summary>What counted as a name</summary>
        <pre>{study.rules}</pre>
      </details>
      <details className="study-details">
        <summary>Every prompt, exactly as sent</summary>
        <ul className="prompts">
          {study.cells.filter((c) => c.model === model && c.prompt).map((c) => (
            <li key={`${c.pronoun}|${c.frame}|${c.condition}`}>
              <b>{c.pronoun} · {c.frame} · {label[c.condition]}</b>
              <pre>{c.prompt}</pre>
            </li>
          ))}
        </ul>
      </details>
    </div>
  )
}

function CellValues({ study, model, name }: { study: NameStudy; model: string; name: string }) {
  const conditions = study.spec.include_bare ? ['model', 'control', 'bare'] : ['model', 'control']
  return (
    <table className="cell-values">
      <thead>
        <tr><th /><th />{conditions.map((c) => <th key={c}>{c === 'model' ? study.spec.subject : c === 'control' ? study.spec.control : 'none'}</th>)}</tr>
      </thead>
      <tbody>
        {study.spec.pronouns.flatMap((p) => study.spec.frames[p].map((f) => (
          <tr key={`${p}|${f}`}>
            <td>{p}</td>
            <td>{f}</td>
            {conditions.map((c) => {
              const cell = study.cells.find((x) => x.model === model && x.pronoun === p && x.frame === f && x.condition === c)
              const v = cell ? value(cell, name) : undefined
              return <td key={c}>{v == null ? '–' : pct(v)}</td>
            })}
          </tr>
        )))}
      </tbody>
    </table>
  )
}
