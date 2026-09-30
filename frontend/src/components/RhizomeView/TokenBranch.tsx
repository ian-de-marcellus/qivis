/**
 * Branching from one token of a model's passage: keep what came before it
 * (still the model's, with its record), then pick the next token from the
 * model's live distribution, or write.
 *
 * In a document, the kept part is a cut of the passage and what follows is a
 * new passage. In a conversation (onBranch), a turn is one node: the new
 * version of the whole turn is generated from the kept part and the choice.
 */

import { useEffect, useRef, useState } from 'react'
import * as api from '../../api/client.ts'
import type { NodeResponse, TokenCandidate } from '../../api/types.ts'
import { useRhizomeStore } from '../../store/rhizomeStore.ts'
import { tokenLabel, wordsOnly } from '../Steering/dasherModel.ts'
import './TokenBranch.css'

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
  onWrite?: (anchorId: string) => void
  /** A turn: generate its new version from the kept tokens and these chosen ones */
  onBranch?: (keep: number, tokenIds: number[], startText: string) => void
  onClose: () => void
}

export function TokenBranch({ rhizomeId, node, index, onWrite, onBranch, onClose }: TokenBranchProps) {
  const showNode = useRhizomeStore(s => s.showNode)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [session, setSession] = useState<string | null>(null)
  const [candidates, setCandidates] = useState<TokenCandidate[] | null>(null)
  const [typed, setTyped] = useState('')
  const [words, setWords] = useState(false)
  const anchorRef = useRef<{ index: number; id: string } | null>(null)
  // A turn: the kept tokens' ids, as the session's tokenizer reads their text
  const keptIdsRef = useRef<number[]>([])
  const sessionRef = useRef<string | null>(null)

  const tokens = node.logprobs?.tokens ?? []
  const original = tokens[index]?.token ?? ''
  const keptText = tokens.slice(0, index).map((t) => t.token).join('')
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
    // A turn continues from its reply's parent, after the kept tokens
    const at = onBranch ? node.parent_id ?? '' : await anchor()
    const s = await api.startSteering(rhizomeId, at || null, { provider: STEERABLE, model: node.model })
    sessionRef.current = s.session_id
    setSession(s.session_id)
    const kept = onBranch && keptText
      ? (await api.steerTokenize(s.session_id, keptText)).map((t) => t.id)
      : []
    keptIdsRef.current = kept
    // Enough to fill the chips after hiding numbers and symbols
    setCandidates(await api.steerNext(s.session_id, kept, 200))
  })

  /** A turn: let go of the session; the new version is generated from the choice */
  const branch = (ids: number[], text: string) => {
    const sid = sessionRef.current
    sessionRef.current = null
    if (sid) api.steerDiscard(sid).catch(() => {})
    onBranch?.(index, ids, keptText + text)
    onClose()
  }

  const commit = (ids: number[], text = '') => run(async () => {
    if (onBranch) {
      branch(ids, text)
      return
    }
    if (!session || ids.length === 0) return
    const made = await api.steerCommit(session, ids, ids.map(() => 'researcher'))
    sessionRef.current = null
    await showNode(made.node_id)
    onClose()
  })

  const commitTyped = () => run(async () => {
    if (!session || !typed) return
    const ids = (await api.steerTokenize(session, typed)).map((t) => t.id)
    if (onBranch) {
      branch(ids, typed)
      return
    }
    const made = await api.steerCommit(session, ids, ids.map(() => 'researcher'))
    sessionRef.current = null
    await showNode(made.node_id)
    onClose()
  })

  const write = () => run(async () => {
    const at = await anchor()
    if (index > 0) await showNode(at)
    onWrite?.(at)
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
            {onBranch ? (
              <button
                disabled={busy}
                onClick={() => branch([], '')}
                title="Keep the turn up to here and let the model go on again"
              >
                Regenerate from here
              </button>
            ) : (
              <button disabled={busy} onClick={write} title="Write your own text from here">
                Write from here
              </button>
            )}
          </>
        )}
        <button className="passage-close" onClick={onClose} aria-label="Cancel branch">
          ×
        </button>
      </div>

      {candidates && (
        <div className="token-branch-candidates">
          <button
            className={`token-chip-filter${words ? ' active' : ''}`}
            onClick={() => setWords((w) => !w)}
            title="Hide numbers and symbols; show the options given the next token is a word"
          >
            words only
          </button>
          {(words ? wordsOnly(candidates) : candidates).slice(0, SHOWN).map((c) => (
            <button
              key={c.id}
              className={`token-chip${c.token === original ? ' token-chip-original' : ''}`}
              disabled={busy}
              onClick={() => commit([c.id], c.token)}
              title={[
                c.token === original && 'What the model sampled here',
                c.conditional && `* given it's a word; the model's own odds: ${((c.raw_prob ?? c.prob) * 100).toFixed(2)}%`,
              ].filter(Boolean).join('. ') || undefined}
            >
              <span className="token-chip-text">{label(c.token)}</span>
              <span className="token-chip-prob">
                {(c.prob * 100).toFixed(1)}%{c.conditional && '*'}
              </span>
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
              placeholder={onBranch ? 'or type your own words' : 'or type tokens'}
              disabled={busy}
            />
          </form>
        </div>
      )}

      {error && <div className="token-branch-error">{error}</div>}
    </div>
  )
}
