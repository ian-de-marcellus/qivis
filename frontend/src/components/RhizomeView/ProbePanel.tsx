/**
 * What would the model say here? Short samples at one point, grouped by the
 * answer each gives (as a small judge model names it), sized by how often
 * it came up. Any sample can become the reply.
 *
 * The samples are the model's; the grouping is the judge's reading of
 * them, and says so.
 */

import { useEffect, useMemo, useState } from 'react'
import * as api from '../../api/client.ts'
import type { Probe } from '../../api/types.ts'
import { useRhizomeStore } from '../../store/rhizomeStore.ts'
import { groupByAnswer } from './probeGroups.ts'
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
  const [probes, setProbes] = useState<Probe[]>([])
  const [shown, setShown] = useState<string | null>(null)
  const [n, setN] = useState(20)
  const [length, setLength] = useState(24)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)

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

  const probeNow = () => run('Sampling and judging…', async () => {
    const made = await api.runProbe(rhizomeId, {
      node_id: nodeId || null, provider, model, n, max_tokens: length,
    })
    setProbes((ps) => [...ps, made])
    setShown(made.probe_id)
    setOpen(null)
  })

  const judge = () => run('Judging…', async () => {
    if (!probe) return
    const judged = await api.judgeProbe(rhizomeId, probe.probe_id)
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

      <div className="probe-controls">
        <label>
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
          {probe ? 'Probe again' : 'Probe'}
        </button>
        {probes.length > 1 && (
          <select value={shown ?? ''} onChange={(e) => setShown(e.target.value)}>
            {probes.map((p, i) => (
              <option key={p.probe_id} value={p.probe_id}>
                probe {i + 1} · {p.samples.length} samples · {p.model.replace(/\.gguf$/, '')}
              </option>
            ))}
          </select>
        )}
      </div>

      {busy && <div className="probe-status">{busy}</div>}
      {error && <div className="probe-error">{error}</div>}

      {probe && (
        <>
          <div className="probe-groups">
            {groups.map((g) => {
              const share = g.indices.length / total
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
                      <span className="probe-share">
                        {Math.round(share * 100)}% · {g.indices.length}/{total}
                      </span>
                    </button>
                  )}
                  {isOpen && (
                    <ul className="probe-samples">
                      {g.indices.map((i) => (
                        <li key={i}>
                          <span className="probe-sample-text">
                            {probe.samples[i].content || <em>(nothing)</em>}
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
