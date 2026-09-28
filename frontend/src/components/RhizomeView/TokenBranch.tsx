/**
 * Branching from one token of a model's passage: keep what came before it
 * (a cut of the passage that is still the model's, with its record), then
 * either pick the next token from the model's live distribution, or write.
 */

import { useEffect, useRef, useState } from 'react'
import * as api from '../../api/client.ts'
import type { NodeResponse, TokenCandidate } from '../../api/types.ts'
import { useRhizomeStore } from '../../store/rhizomeStore.ts'
import { tokenLabel } from '../Steering/dasherModel.ts'

// Next-token distributions come from llama.cpp only, for now
const STEERABLE = 'llamacpp'
const SHOWN = 12

const label = (token: string) => tokenLabel(token) || '(empty)'

interface TokenBranchProps {
  rhizomeId: string
  node: NodeResponse
  /** Branch before this token (0: in place of the whole passage) */
  index: number
  /** Where writing goes: under this node ('' for the beginning) */
  onWrite: (anchorId: string) => void
  onClose: () => void
}

export function TokenBranch({ rhizomeId, node, index, onWrite, onClose }: TokenBranchProps) {
  const showNode = useRhizomeStore(s => s.showNode)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [session, setSession] = useState<string | null>(null)
  const [candidates, setCandidates] = useState<TokenCandidate[] | null>(null)
  const [typed, setTyped] = useState('')
  const anchorRef = useRef<{ index: number; id: string } | null>(null)
  const sessionRef = useRef<string | null>(null)

  const tokens = node.logprobs?.tokens ?? []
  const original = tokens[index]?.token ?? ''
  const canPick = node.provider === STEERABLE

  // A new cut point starts over; a session left open is let go
  useEffect(() => {
    setCandidates(null)
    setError(null)
    setTyped('')
    return () => {
      const sid = sessionRef.current
      sessionRef.current = null
      setSession(null)
      if (sid) api.steerDiscard(sid).catch(() => {})
    }
  }, [index])

  /** The node to branch under: the passage's parent, or its cut before `index` (made once). */
  const anchor = async (): Promise<string> => {
    if (index === 0) return node.parent_id ?? ''
    if (anchorRef.current?.index === index) return anchorRef.current.id
    const cut = await api.cutNode(rhizomeId, node.node_id, index)
    anchorRef.current = { index, id: cut.node_id }
    return cut.node_id
  }

  const run = async (step: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await step()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const pick = () => run(async () => {
    const at = await anchor()
    const s = await api.startSteering(rhizomeId, at || null, { provider: STEERABLE, model: node.model })
    sessionRef.current = s.session_id
    setSession(s.session_id)
    setCandidates(await api.steerNext(s.session_id, [], SHOWN))
  })

  const commit = (ids: number[]) => run(async () => {
    if (!session || ids.length === 0) return
    const made = await api.steerCommit(session, ids, ids.map(() => 'researcher'))
    sessionRef.current = null
    await showNode(made.node_id)
    onClose()
  })

  const commitTyped = () => run(async () => {
    if (!session || !typed) return
    const ids = (await api.steerTokenize(session, typed)).map((t) => t.id)
    const made = await api.steerCommit(session, ids, ids.map(() => 'researcher'))
    sessionRef.current = null
    await showNode(made.node_id)
    onClose()
  })

  const write = () => run(async () => {
    const at = await anchor()
    if (index > 0) await showNode(at)
    onWrite(at)
    onClose()
  })

  return (
    <div className="token-branch">
      <div className="passage-bar-row">
        <span className="token-branch-label">
          Branch before <code>{label(original)}</code>
        </span>
        <span className="passage-bar-spacer" />
        {candidates == null && (
          <>
            <button
              disabled={busy || !canPick}
              onClick={pick}
              title={canPick
                ? 'Choose the next token yourself, from what the model would say here'
                : 'Picking tokens needs a local (llama.cpp) model'}
            >
              Pick the next token
            </button>
            <button disabled={busy} onClick={write} title="Write your own text from here">
              Write from here
            </button>
          </>
        )}
        <button className="passage-close" onClick={onClose} aria-label="Cancel branch">
          ×
        </button>
      </div>

      {candidates && (
        <div className="token-branch-candidates">
          {candidates.map((c) => (
            <button
              key={c.id}
              className={`token-chip${c.token === original ? ' token-chip-original' : ''}`}
              disabled={busy}
              onClick={() => commit([c.id])}
              title={c.token === original ? 'What the model sampled here' : undefined}
            >
              <span className="token-chip-text">{label(c.token)}</span>
              <span className="token-chip-prob">{(c.prob * 100).toFixed(1)}%</span>
            </button>
          ))}
          <form
            className="token-chip-typed"
            onSubmit={(e) => {
              e.preventDefault()
              commitTyped()
            }}
          >
            <input
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder="or type tokens"
              disabled={busy}
            />
          </form>
        </div>
      )}

      {error && <div className="token-branch-error">{error}</div>}
    </div>
  )
}
