/**
 * What would the model say here? Short samples at one point, grouped by the
 * answer each gives (as a small judge model names it), sized by how often
 * it came up. Any sample can become the reply.
 *
 * Or, exactly (llama.cpp models): every one-line answer down to a probability
 * epsilon, with its exact probability; the pruned rest estimated from tail
 * rollouts (qivis.probes.exact).
 *
 * The samples and probabilities are the model's; the grouping is the judge's
 * reading of them, and says so.
 */

import { useEffect, useMemo, useState } from 'react'
import * as api from '../../api/client.ts'
import type { ModelEntry, Probe } from '../../api/types.ts'
import { useRhizomeStore } from '../../store/rhizomeStore.ts'
import { LogprobOverlay } from './LogprobOverlay.tsx'
import { groupByAnswer, shareRange } from './probeGroups.ts'
import './ProbePanel.css'

interface ProbePanelProps {
  rhizomeId: string
  /** The point probed: what comes after this node ('' for the beginning) */
  nodeId: string
  provider: string
  model: string
  onClose: () => void
}

export function ProbePanel({ rhizomeId, nodeId, provider, model, onClose }: ProbePanelProps) {
  const showNode = useRhizomeStore(s => s.showNode)
  const pointNode = useRhizomeStore(s => s.currentRhizome?.nodes.find((n) => n.node_id === nodeId))
  const [probes, setProbes] = useState<Probe[]>([])
  const [shown, setShown] = useState<string | null>(null)
  const [n, setN] = useState(20)
  const [length, setLength] = useState(24)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [mode, setMode] = useState<'sample' | 'exact'>('sample')
  const [epsilon, setEpsilon] = useState(0.001)
  const [tail, setTail] = useState(100)
  const [menu, setMenu] = useState('')
  const [grain, setGrain] = useState('')
  const [judgeId, setJudgeId] = useState('')  // '' = the local judge
  const [judges, setJudges] = useState<ModelEntry[]>([])
  const exactAllowed = provider === 'llamacpp'

  // Models that can judge exact probes besides the local one: chat models from other providers
  useEffect(() => {
    api.getModels()
      .then((ms) => setJudges(ms.filter((m) => m.provider !== 'llamacpp' && m.mode === 'chat')))
      .catch(() => {})
  }, [])

  // Earlier probes at this point
  useEffect(() => {
    let live = true
    api.listProbes(rhizomeId)
      .then((all) => {
        if (!live) return
        const here = all.filter((p) => (p.node_id ?? '') === nodeId)
        setProbes(here)
        setShown((id) => id ?? here.at(-1)?.probe_id ?? null)
      })
      .catch(() => {})
    return () => { live = false }
  }, [rhizomeId, nodeId])

  const probe = probes.find((p) => p.probe_id === shown) ?? null
  // The settings start in the mode of the probe on show
  const shownMode = probe?.mode
  useEffect(() => {
    if (shownMode) setMode(shownMode)
  }, [shownMode])
  const groups = useMemo(() => (probe ? groupByAnswer(probe) : []), [probe])

  const run = async (step: string, work: () => Promise<void>) => {
    setBusy(step)
    setError(null)
    try {
      await work()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  const judgeChoice = () => {
    const j = judges.find((m) => m.id === judgeId)
    return j ? { provider: j.provider, model: j.model } : null
  }

  const probeNow = () => run(mode === 'exact' ? 'Enumerating, sampling the tail, judging… (can take a minute or two)' : 'Sampling and judging…', async () => {
    const menuItems = menu.split('\n').map((m) => m.trim()).filter(Boolean)
    const made = await api.runProbe(rhizomeId, mode === 'exact'
      ? {
        node_id: nodeId || null, provider, model, mode, max_tokens: length, epsilon, tail,
        menu: menuItems.length ? menuItems : null, judge: judgeChoice(), grain: grain.trim() || null,
      }
      : { node_id: nodeId || null, provider, model, n, max_tokens: length })
    setProbes((ps) => [...ps, made])
    setShown(made.probe_id)
    setOpen(null)
  })

  const judge = () => run('Judging…', async () => {
    if (!probe) return
    const judged = await api.judgeProbe(rhizomeId, probe.probe_id, probe.mode === 'exact' ? judgeChoice() : null)
    setProbes((ps) => ps.map((p) => (p.probe_id === judged.probe_id ? judged : p)))
  })

  const continueFrom = (index: number) => run('Continuing…', async () => {
    if (!probe) return
    const node = await api.continueFromProbeSample(rhizomeId, probe.probe_id, index)
    await showNode(node.node_id)
    onClose()
  })

  const total = probe?.samples.length ?? 0

  return (
    <div className="probe-panel">
      <div className="probe-head">
        <span className="probe-title">What would {model.replace(/\.gguf$/, '') || 'the model'} say here?</span>
        <button className="probe-close" onClick={onClose} aria-label="Close probe">×</button>
      </div>

      <div className="probe-point">
        {nodeId && pointNode
          ? <>after <q>…{(pointNode.edited_content ?? pointNode.content).slice(-60)}</q></>
          : 'at the very beginning: a blank page'}
      </div>

      {exactAllowed && (
        <div className="probe-modes">
          <button className={mode === 'sample' ? 'on' : ''} onClick={() => setMode('sample')}>sampled</button>
          <button className={mode === 'exact' ? 'on' : ''} onClick={() => setMode('exact')}
            title="Every one-line answer down to a probability ε, exactly; the rest estimated from rollouts">
            exact
          </button>
        </div>
      )}

      <div className="probe-controls">
        {mode === 'exact' ? (
          <>
            <label title="Answers less likely than this aren't enumerated (their total is reported, and sampled)">
              ε
              <input type="number" min={0.000001} max={0.5} step={0.0001} value={epsilon}
                onChange={(e) => setEpsilon(Math.max(0.000001, Math.min(0.5, Number(e.target.value) || 0.001)))} />
            </label>
            <label title="Rollouts that estimate how the pruned probability splits by answer">
              tail
              <input type="number" min={0} max={1000} value={tail}
                onChange={(e) => setTail(Math.max(0, Math.min(1000, Number(e.target.value) || 0)))} />
            </label>
          </>
        ) : null}
        <label style={mode === 'exact' ? { display: 'none' } : undefined}>
          samples
          <input type="number" min={1} max={64} value={n}
            onChange={(e) => setN(Math.max(1, Math.min(64, Number(e.target.value) || 1)))} />
        </label>
        <label>
          up to
          <input type="number" min={1} max={256} value={length}
            onChange={(e) => setLength(Math.max(1, Math.min(256, Number(e.target.value) || 1)))} />
          tokens
        </label>
        <button className="probe-run" onClick={probeNow} disabled={busy != null}>
          {mode === 'exact' ? 'Compute' : probe ? 'Probe again' : 'Probe'}
        </button>
        {probes.length > 1 && (
          <select value={shown ?? ''} onChange={(e) => setShown(e.target.value)}>
            {probes.map((p, i) => (
              <option key={p.probe_id} value={p.probe_id}>
                probe {i + 1} · {p.mode === 'exact' ? `exact, ε ${p.exact?.settings.epsilon}` : `${p.samples.length} samples`} · {p.model.replace(/\.gguf$/, '')}
              </option>
            ))}
          </select>
        )}
      </div>

      {mode === 'exact' && (
        <div className="probe-exact-options">
          <label>
            answers to choose from <span className="probe-hint">(optional, one per line; otherwise the judge names them. Answers off the list are named and grouped as “other: …”, so no catch-all is needed)</span>
            <textarea rows={3} value={menu} onChange={(e) => setMenu(e.target.value)}
              placeholder={'an AI, model or program\na person or human\na mind, consciousness or awareness'} />
          </label>
          {!menu.trim() && (
            <label>
              grouping <span className="probe-hint">(optional: how fine, in words)</span>
              <input type="text" value={grain} onChange={(e) => setGrain(e.target.value)}
                placeholder="e.g. dog breeds count as dog" />
            </label>
          )}
          <label>
            judge
            <select value={judgeId} onChange={(e) => setJudgeId(e.target.value)}>
              <option value="">local (Qwen3 4B, or 1.7B on CPU)</option>
              {judges.map((m) => <option key={m.id} value={m.id}>{m.label} ({m.provider})</option>)}
            </select>
          </label>
        </div>
      )}

      {busy && <div className="probe-status">{busy}</div>}
      {error && <div className="probe-error">{error}</div>}

      {probe && probe.mode === 'exact' && probe.exact && (
        <ExactResult probe={probe} open={open} setOpen={setOpen} busy={busy != null}
          continueFrom={continueFrom} judge={judge} />
      )}

      {probe && probe.mode !== 'exact' && (
        <>
          <div className="probe-groups">
            {groups.map((g) => {
              const share = g.indices.length / total
              const [lo, hi] = shareRange(g.indices.length, total)
              const isOpen = open === g.answer || !probe.judge
              return (
                <div key={g.answer} className="probe-group">
                  {probe.judge && (
                    <button
                      className={`probe-group-row${isOpen ? ' open' : ''}`}
                      onClick={() => setOpen(open === g.answer ? null : g.answer)}
                    >
                      <span className="probe-bar" style={{ width: `${share * 100}%` }} />
                      <span className="probe-answer">{g.answer}</span>
                      <span
                        className="probe-share"
                        title={`${g.indices.length} of ${total} draws; the true share is likely between ${Math.round(lo * 100)}% and ${Math.round(hi * 100)}%`}
                      >
                        {Math.round(share * 100)}%
                        <span className="probe-range"> ({Math.round(lo * 100)}–{Math.round(hi * 100)}%)</span>
                        {' '}· {g.indices.length}/{total}
                      </span>
                    </button>
                  )}
                  {isOpen && (
                    <ul className="probe-samples">
                      {g.indices.map((i) => (
                        <li key={i}>
                          <span className="probe-sample-text">
                            {probe.samples[i].logprobs && probe.samples[i].content
                              ? <LogprobOverlay logprobs={probe.samples[i].logprobs!} content={probe.samples[i].content} />
                              : probe.samples[i].content || <em>(nothing)</em>}
                            {probe.samples[i].finish_reason === 'length' && <span className="probe-more">…</span>}
                          </span>
                          <button
                            onClick={() => continueFrom(i)}
                            disabled={busy != null}
                            title="Make this the reply (recorded as sampled, noting this probe)"
                          >
                            Continue
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )
            })}
          </div>

          <div className="probe-foot">
            {total} samples at temperature 1 from {probe.model.replace(/\.gguf$/, '')}
            {probe.asked != null && probe.asked > total && (
              <span className="probe-failed"> ({probe.asked - total} of {probe.asked} failed)</span>
            )}
            {' '}· ranges are 95% intervals for the share · hover a word for its probability
            {probe.judge
              ? <> · grouped by {probe.judge.model.replace(/\.gguf$/, '')} (its reading, not the model&apos;s)</>
              : (
                <>
                  {' '}· not grouped (no judge model was available){' '}
                  <button onClick={judge} disabled={busy != null}>Group now</button>
                </>
              )}
          </div>
        </>
      )}
    </div>
  )
}

const pct = (x: number) => (x > 0 && x < 0.001 ? '<0.1%' : `${(x * 100).toFixed(1)}%`)

interface ExactResultProps {
  probe: Probe
  open: string | null
  setOpen: (a: string | null) => void
  busy: boolean
  continueFrom: (index: number) => void
  judge: () => void
}

/** An exact probe: each answer's exact probability, the range the pruned mass allows, the tail's estimate. */
// Groups smaller than this are folded into one row ("smaller answers")
const SMALL = 0.01

function ExactResult({ probe, open, setOpen, busy, continueFrom, judge }: ExactResultProps) {
  const ex = probe.exact!
  const [showSmall, setShowSmall] = useState(false)
  const big = ex.groups.filter((g) => g.exact + g.tail >= SMALL || g.answer === 'no answer')
  const small = ex.groups.filter((g) => !big.includes(g))
  const smallMass = small.reduce((t, g) => t + g.exact + g.tail, 0)
  return (
    <>
      <div className="probe-groups">
        {[...big, ...(showSmall ? small : [])].map((g) => {
          const isOpen = open === g.answer || !probe.judge
          return (
            <div key={g.answer} className="probe-group">
              {probe.judge && (
                <button className={`probe-group-row${isOpen ? ' open' : ''}`}
                  onClick={() => setOpen(open === g.answer ? null : g.answer)}>
                  <span className="probe-bar" style={{ width: `${g.exact * 100}%` }} />
                  <span className="probe-bar probe-bar-tail" style={{ left: `${g.exact * 100}%`, width: `${g.tail * 100}%` }} />
                  <span className="probe-answer">{g.answer}</span>
                  <span className="probe-share"
                    title={`exactly ${pct(g.exact)} from enumerated answers; about ${pct(g.tail)} more estimated from the pruned ${pct(ex.pruned)}. Its true share is between ${pct(g.exact)} and ${pct(g.exact + ex.pruned)}.`}>
                    {pct(g.exact + g.tail)}
                    <span className="probe-range"> ({pct(g.exact)} exact{g.tail > 0 ? ` + ≈${pct(g.tail)} tail` : ''})</span>
                  </span>
                </button>
              )}
              {isOpen && (
                <ul className="probe-samples">
                  {g.labels.flatMap((lab) => [
                    ...(g.labels.length > 1 || lab.label !== g.answer
                      ? [<li key={`l-${lab.label}`} className="probe-label">“{lab.label}” · {pct(lab.exact)}{lab.tail > 0 ? ` + ≈${pct(lab.tail)}` : ''}</li>]
                      : []),
                    ...[...lab.items].sort((a, b) => ex.items[b].mass - ex.items[a].mass).slice(0, 12).map((i) => (
                      <li key={i}>
                        <span className="probe-sample-text">
                          {ex.items[i].text || <em>(nothing)</em>}
                          {ex.items[i].finish === 'length' && <span className="probe-more">…</span>}
                          <span className="probe-mass">
                            {ex.items[i].kind === 'leaf' ? pct(ex.items[i].mass) : `tail ≈${pct(ex.items[i].mass)}`}
                          </span>
                        </span>
                        <button onClick={() => continueFrom(i)} disabled={busy}
                          title={ex.items[i].kind === 'leaf'
                            ? 'Make this the reply (recorded as enumerated, with its exact probability, noting this probe)'
                            : 'Make this the reply (recorded as a tail rollout, noting this probe)'}>
                          Continue
                        </button>
                      </li>
                    )),
                  ])}
                </ul>
              )}
            </div>
          )
        })}
        {small.length > 0 && (
          <button className="probe-group-row probe-small" onClick={() => setShowSmall(!showSmall)}>
            <span className="probe-answer">
              {showSmall ? 'hide' : 'show'} {small.length} smaller answers (each under {pct(SMALL)}, {pct(smallMass)} together)
            </span>
          </button>
        )}
      </div>

      <div className="probe-foot">
        {pct(ex.explored)} enumerated exactly (one-line answers down to ε = {ex.settings.epsilon}, {ex.lookups} lookups
        {ex.stopped_early ? ', stopped at the lookup limit' : ''})
        {ex.cut_off > 0 && <>, {pct(ex.cut_off)} of it cut off at {ex.settings.max_tokens} tokens</>}
        {' '}· the other {pct(ex.pruned)} estimated from {ex.items.filter((x) => x.kind === 'tail').length} rollouts
        {' '}· temperature 1, nothing truncated, {probe.model.replace(/\.gguf$/, '')}
        {probe.judge
          ? <> · {probe.judge.menu ? 'matched to your answers' : 'named and grouped'} by {probe.judge.model.replace(/\.gguf$/, '')}
            {probe.judge.bucket_judge?.model && probe.judge.bucket_judge.model !== probe.judge.model
              ? <> (grouped by {probe.judge.bucket_judge.model})</> : null} (its reading, not the model&apos;s){' '}
            <button onClick={judge} disabled={busy}>Judge again</button></>
          : <> · not grouped (no judge was available){' '}<button onClick={judge} disabled={busy}>Group now</button></>}
      </div>
    </>
  )
}
