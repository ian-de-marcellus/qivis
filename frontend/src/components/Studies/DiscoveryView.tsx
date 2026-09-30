/**
 * Name discovery: names found by what they lean toward (the backend's
 * qivis/names/discover.py), with a form to start one and a way to send the
 * chosen names to studies, where they're scored exactly in every cell.
 *
 * The search is a beam, not exhaustive: its numbers are its own estimates
 * (over the frames it compared); a study's are the exact record.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import * as api from '../../api/client.ts'
import type { NameDiscovery, NameStudySummary } from '../../api/types.ts'

const times = (log: number | undefined) => {
  if (log == null) return '–'
  const x = Math.exp(log)
  return x > 10_000 ? '>10,000×' : x >= 10 || x < 0.1 ? `${x.toPrecision(2)}×` : `${x.toFixed(2)}×`
}
const pct = (log: number) => {
  const p = Math.exp(log)
  return p >= 0.001 ? `${(p * 100).toFixed(2)}%` : `${(p * 100).toExponential(1)}%`
}
const short = (s: string) => s.replace(/^Names for /, '').replace(/\s*\(.*\)$/, '')

export function DiscoveryView({ discoveryId, studies, onAdded, excluded }: {
  discoveryId: string
  studies: NameStudySummary[]
  onAdded: () => void
  excluded: string[]
}) {
  const [d, setD] = useState<NameDiscovery | null>(null)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [targets, setTargets] = useState<Set<string>>(new Set())
  const [note, setNote] = useState<string | null>(null)

  const load = useCallback(() => {
    api.getNameDiscovery(discoveryId).then(setD).catch((e) => setNote(String(e)))
  }, [discoveryId])
  useEffect(() => { load() }, [load])
  useEffect(() => {
    if (d?.status !== 'running') return
    const t = setInterval(load, 4000)
    return () => clearInterval(t)
  }, [d?.status, load])

  if (!d) return <div className="hint">Loading…</div>
  const failures = d.prompts.failure_titles ?? []

  const toggle = (set: Set<string>, item: string, update: (s: Set<string>) => void) => {
    const next = new Set(set)
    if (next.has(item)) next.delete(item)
    else next.add(item)
    update(next)
  }

  const add = async () => {
    const names = [...picked]
    for (const id of targets) await api.extendNameStudy(id, names)
    setNote(`Added ${names.length} name${names.length === 1 ? '' : 's'} to ${targets.size} stud${targets.size === 1 ? 'y' : 'ies'}; they'll be scored in every cell.`)
    onAdded()
  }

  return (
    <div className="study-results">
      <div className="study-head">
        <h3>{d.title}</h3>
        <span className={`study-status ${d.status}`} /> {d.status}
      </div>
      <p className="hint">
        "{d.spec.pronoun}" · weights: vs control {d.spec.weights.ai}, vs "it" {d.spec.weights.gender},
        {' '}vs the worst of {failures.map(short).join(' / ') || 'no failure modes'} {d.spec.weights.character}
        {' '}· beam {d.spec.beam}, up to {d.spec.depth} tokens · {d.queries} lookups.
        {' '}A beam search: its numbers are estimates over its frames; add names to a study for the exact record.
      </p>
      {d.progress && (
        <div className="study-progress">
          {d.progress.phase} ({d.progress.done}/{d.progress.of})
          <div className="bar"><div style={{ width: `${(100 * d.progress.done) / Math.max(1, d.progress.of)}%` }} /></div>
        </div>
      )}
      {d.error && <div className="study-error">{d.error}</div>}

      {d.results && (
        <>
          <div className="names-table">
            <table>
              <thead>
                <tr>
                  <th />
                  <th>name</th>
                  <th title="Geometric mean over frames, for the description">probability</th>
                  <th>× vs control</th>
                  <th>{d.spec.pronoun} ÷ it</th>
                  <th title="Against the failure mode it leans most toward">× vs worst failure</th>
                  <th title="The search's score (natural log)">score</th>
                </tr>
              </thead>
              <tbody>
                {d.results.map((r) => (
                  <tr
                    key={r.name}
                    className={excluded.includes(r.name) ? 'excluded' : ''}
                    onClick={() => { if (!excluded.includes(r.name)) toggle(picked, r.name, setPicked) }}
                    title={excluded.includes(r.name) ? 'Excluded (see Excluded names)' : undefined}
                  >
                    <td><input type="checkbox" readOnly checked={picked.has(r.name)} disabled={excluded.includes(r.name)} /></td>
                    <td className="name">{r.name}</td>
                    <td>{pct(r.log_p)}</td>
                    <td className={r.ai > 0 ? 'up' : 'down'}>{times(r.ai)}</td>
                    <td className={(r.gender ?? 0) > 0 ? 'up' : 'down'}>{times(r.gender)}</td>
                    <td className={(r.character ?? 0) > 0 ? 'up' : 'down'}>{times(r.character)}</td>
                    <td>{r.score.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="compare-row">
            <span>Add the {picked.size} chosen to:</span>
            {studies.map((s) => (
              <label key={s.study_id} className="choice">
                <input type="checkbox" checked={targets.has(s.study_id)} onChange={() => toggle(targets, s.study_id, setTargets)} />
                {short(s.title)}
              </label>
            ))}
            <button className="run" disabled={picked.size === 0 || targets.size === 0} onClick={add}>Add</button>
          </div>
        </>
      )}
      {note && <p className="hint">{note}</p>}
    </div>
  )
}

export function NewDiscovery({ studies, onCreated }: {
  studies: NameStudySummary[]
  onCreated: (id: string) => void
}) {
  const [studyId, setStudyId] = useState(studies[0]?.study_id ?? '')
  const [failuresPicked, setFailures] = useState<string[]>([])
  const [pronoun, setPronoun] = useState('she')
  const [weights, setWeights] = useState({ ai: 1, gender: 1, character: 1 })
  const [beam, setBeam] = useState(40)
  const [error, setError] = useState<string | null>(null)
  const study = useMemo(() => studies.find((s) => s.study_id === studyId), [studies, studyId])

  const run = async () => {
    setError(null)
    try {
      const made = await api.createNameDiscovery({
        title: `Discovery: ${pronoun}, ${short(study?.title ?? '')}`,
        model: study?.models[0] ?? '', pronoun, study_id: studyId,
        failure_study_ids: failuresPicked, weights, beam,
      })
      onCreated(made.discovery_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const slider = (key: keyof typeof weights, label: string) => (
    <label className="field">
      <span>{label}: {weights[key].toFixed(1)}</span>
      <input type="range" min={0} max={4} step={0.1} value={weights[key]}
        onChange={(e) => setWeights({ ...weights, [key]: Number(e.target.value) })} />
    </label>
  )

  return (
    <div className="new-study">
      <p className="hint">
        Search for names by what they lean toward: each weight is how much of that lean is worth one unit of
        likelihood (1: a name twice as leaning is worth being half as likely).
      </p>
      <label className="field">
        <span>Description (from study)</span>
        <select value={studyId} onChange={(e) => setStudyId(e.target.value)}>
          {studies.map((s) => <option key={s.study_id} value={s.study_id}>{short(s.title)}</option>)}
        </select>
      </label>
      <div className="field">
        <span>Failure modes (their descriptions; a name is scored against the worst)</span>
        <div className="choices">
          {studies.filter((s) => s.study_id !== studyId).map((s) => (
            <label key={s.study_id} className="choice">
              <input type="checkbox" checked={failuresPicked.includes(s.study_id)}
                onChange={() => setFailures(failuresPicked.includes(s.study_id)
                  ? failuresPicked.filter((x) => x !== s.study_id) : [...failuresPicked, s.study_id])} />
              {short(s.title)}
            </label>
          ))}
        </div>
      </div>
      <label className="field narrow">
        <span>Pronoun</span>
        <select value={pronoun} onChange={(e) => setPronoun(e.target.value)}>
          {['she', 'he', 'they', 'it'].map((p) => <option key={p}>{p}</option>)}
        </select>
      </label>
      <div className="field-row">
        {slider('ai', 'vs the control')}
        {slider('gender', `${pronoun} over "it"`)}
        {slider('character', 'vs the worst failure mode')}
      </div>
      <label className="field narrow">
        <span>Beam</span>
        <input type="number" min={5} max={400} value={beam} onChange={(e) => setBeam(Number(e.target.value) || 40)} />
      </label>
      {error && <div className="study-error">{error}</div>}
      <div className="run-row">
        <button className="run" onClick={run} disabled={!studyId}>Search</button>
        <span className="hint">About 5 to 15 minutes on a 7B.</span>
      </div>
    </div>
  )
}
