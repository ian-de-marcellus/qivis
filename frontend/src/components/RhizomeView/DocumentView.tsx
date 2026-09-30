/**
 * DocumentView — renders document-template rhizomes as one continuous text.
 *
 * The document template joins every part exactly as written, so this view
 * does too: the opening text, then each node on the active path as an inline
 * passage, with no speakers or turn breaks. Whose words are whose stays
 * visible (the researcher's are tinted, the model's are plain or heatmapped).
 * Clicking a passage selects it: its branches, regenerate, continue or steer
 * from there, and exactly what the model saw. In a selected passage of the
 * model's, clicking a token branches before it. Writing happens at the end,
 * or at a branch point.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as api from '../../api/client.ts'
import type { GenerateRequest, NodeResponse } from '../../api/types.ts'
import { useRhizomeStore, useRhizomeData, useStreamingState } from '../../store/rhizomeStore.ts'
import { BranchIndicator } from './BranchIndicator.tsx'
import { ForkPanelFor, InspectedContext } from './ConversationParts.tsx'
import { GenerationErrorPanel } from './GenerationErrorPanel.tsx'
import { LogprobOverlay } from './LogprobOverlay.tsx'
import { averageCertainty } from './logprobColor.ts'
import { formatSamplingMeta, formatUsage } from './nodeFormat.ts'
import { ProbePanel } from './ProbePanel.tsx'
import { PromptTextViewer } from './PromptTextViewer.tsx'
import { TokenBranch } from './TokenBranch.tsx'
import { useAutoScroll, useConversationView, useScrollToNode } from './useViewShared.ts'
import './ChatView.css'
import './MessageInput.css'
import './DocumentView.css'

const HEATMAP_KEY = 'qivis.document.heatmap'

function readHeatmapPref(): boolean {
  try {
    return localStorage.getItem(HEATMAP_KEY) === '1'
  } catch {
    return false
  }
}

const textOf = (node: NodeResponse) => node.edited_content ?? node.content
const isModel = (node: NodeResponse) => node.role === 'assistant' && node.mode !== 'manual'
/** A model passage whose tokens are its text: shown token by token, and branchable */
const tokenized = (node: NodeResponse) =>
  isModel(node) && (node.logprobs?.tokens.length ?? 0) > 0 && node.edited_content == null

function whoWrote(node: NodeResponse): string {
  if (!isModel(node)) return 'your text'
  const by = node.mode === 'steered' ? 'steered with ' : ''
  return `${by}${node.model ?? 'model'}`
}

export function DocumentView() {
  const { currentRhizome } = useRhizomeData()
  const fetchProviders = useRhizomeStore(s => s.fetchProviders)
  const view = useConversationView()
  const { nodes, path, childMap, excludedIds, leafNodeId, branchDefaults } = view
  const {
    isGenerating, streamingContent, streamingContents, activeStreamIndex,
    generationError, stopGeneration,
  } = useStreamingState()
  const regenerate = useRhizomeStore(s => s.regenerate)
  const selectBranch = useRhizomeStore(s => s.selectBranch)
  const openSteer = useRhizomeStore(s => s.openSteer)
  const forkAndGenerate = useRhizomeStore(s => s.forkAndGenerate)
  const showNode = useRhizomeStore(s => s.showNode)
  const clearGenerationError = useRhizomeStore(s => s.clearGenerationError)

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [showDetails, setShowDetails] = useState(false)
  const [heatmap, setHeatmap] = useState(readHeatmapPref)
  // A token to branch before, in the selected passage
  const [cut, setCut] = useState<{ nodeId: string; index: number } | null>(null)
  // Writing at a branch point instead of the end ('' for the beginning)
  const [writeAfter, setWriteAfter] = useState<string | null>(null)
  const composerRef = useRef<HTMLTextAreaElement>(null)
  // Probing what comes next after this node ('' for the beginning)
  const [probeAt, setProbeAt] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  useAutoScroll(bottomRef, path.length)
  useScrollToNode()

  useEffect(() => {
    fetchProviders()
  }, [fetchProviders])

  const toggleHeatmap = () => {
    setHeatmap((on) => {
      try {
        localStorage.setItem(HEATMAP_KEY, on ? '0' : '1')
      } catch { /* a convenience only */ }
      return !on
    })
  }

  const selected = path.find((n) => n.node_id === selectedId) ?? null

  const select = (node: NodeResponse) => {
    // Selecting text to copy shouldn't also select the passage
    if (window.getSelection()?.toString()) return
    setSelectedId((id) => (id === node.node_id ? null : node.node_id))
    setShowDetails(false)
    setCut(null)
  }

  // Writing at a branch point shows the text only up to it
  const shown = useMemo(() => {
    if (writeAfter == null) return path
    if (writeAfter === '') return []
    const at = path.findIndex((n) => n.node_id === writeAfter)
    return at === -1 ? path : path.slice(0, at + 1)
  }, [path, writeAfter])
  const writeUnder = writeAfter ?? leafNodeId ?? ''

  /** Generation settings: this passage's model, else the branch's. */
  const overridesLike = useCallback((like?: NodeResponse): GenerateRequest => {
    const useOwn = like != null && isModel(like) && like.provider != null
    const provider = useOwn ? like.provider : branchDefaults.provider
    const model = useOwn ? like.model : branchDefaults.model
    return {
      ...(provider ? { provider } : {}),
      ...(model ? { model } : {}),
      stream: currentRhizome?.metadata?.stream_responses !== false,
    }
  }, [branchDefaults, currentRhizome])

  /** Generate under parentId ('' for the beginning). */
  const generateUnder = useCallback((parentId: string, like?: NodeResponse) => {
    regenerate(parentId, overridesLike(like))
  }, [overridesLike, regenerate])

  // Writing: what's typed goes under the leaf, or the branch point
  const addText = async (text: string): Promise<string | null> => {
    if (!currentRhizome) return null
    const made = await api.createNode(currentRhizome.rhizome_id, {
      content: text, role: 'user', parent_id: writeUnder || undefined,
    })
    setWriteAfter(null)
    await showNode(made.node_id)
    return made.node_id
  }
  const composer = {
    continue: (text: string) => {
      setWriteAfter(null)
      if (text) forkAndGenerate(writeUnder, text, overridesLike())
      else generateUnder(writeUnder)
    },
    add: (text: string) => { addText(text) },
    steer: async (text: string) => {
      const at = text ? await addText(text) : writeUnder
      if (at != null) openSteer(at)
    },
    // What's typed is added first, so the probe is of what comes after it
    probe: async (text: string) => {
      const at = text ? await addText(text) : writeUnder
      if (at != null) setProbeAt(at)
    },
  }

  useEffect(() => {
    if (!selectedId) return
    const onKey = (e: KeyboardEvent) => {
      // The steering view's own Esc closes it, not this
      if (e.key === 'Escape' && useRhizomeStore.getState().steerTarget == null) {
        setSelectedId(null)
        setCut(null)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selectedId])

  const opening = currentRhizome?.default_system_prompt ?? ''
  const live = streamingContents[activeStreamIndex] ?? streamingContent
  const empty = shown.length === 0 && !opening && !isGenerating

  return (
    <div className="document-view">
      <div className="linear-view">
        <div className="messages">
          <div className="document-toolbar">
            <span className="document-legend">
              <span className="doc-swatch doc-swatch-researcher" /> yours
              <span className="doc-swatch doc-swatch-model" /> the model's
            </span>
            <button
              className={`document-toggle${heatmap ? ' active' : ''}`}
              onClick={toggleHeatmap}
              title="Color the model's tokens by probability"
            >
              Heatmap
            </button>
          </div>

          <div className="document-text">
            {empty && (
              <span className="document-placeholder">
                Nothing yet. Write the beginning below, or let the model start.
              </span>
            )}
            {opening && (
              <span
                className="doc-span doc-researcher doc-opening"
                title="Opening text (edit in rhizome settings)"
              >
                {opening}
              </span>
            )}
            {shown.map((node) => {
              const siblings = childMap.get(node.parent_id) ?? []
              const index = siblings.findIndex((s) => s.node_id === node.node_id)
              const classes = [
                'doc-span',
                isModel(node) ? 'doc-model' : 'doc-researcher',
                node.node_id === selectedId && 'doc-selected',
                excludedIds.has(node.node_id) && 'doc-excluded',
              ].filter(Boolean).join(' ')
              return (
                <span key={node.node_id} className="doc-passage">
                  {siblings.length > 1 && (
                    <span
                      className="doc-branch-mark"
                      title={`Branch ${index + 1} of ${siblings.length}: select the passage to switch`}
                      onClick={() => select(node)}
                    >
                      {index + 1}/{siblings.length}
                    </span>
                  )}
                  <span
                    className={classes}
                    data-node-id={node.node_id}
                    onClick={() => select(node)}
                  >
                    {tokenized(node) && (heatmap || node.node_id === selectedId)
                      ? (
                        <LogprobOverlay
                          logprobs={node.logprobs!}
                          content={node.content}
                          plain={!heatmap}
                          onTokenClick={node.node_id === selectedId && !isGenerating
                            ? (i) => setCut({ nodeId: node.node_id, index: i })
                            : undefined}
                          cutAt={cut?.nodeId === node.node_id ? cut.index : null}
                        />
                      )
                      : textOf(node)}
                  </span>
                </span>
              )
            })}
            {isGenerating && (
              <span className="doc-span doc-model doc-streaming">
                {live}
                <span className="doc-caret" />
              </span>
            )}
          </div>

          {!isGenerating && generationError && (
            <GenerationErrorPanel
              generationError={generationError}
              leafNodeId={leafNodeId}
              onRetry={regenerate}
              onChangeSettings={view.fork.setForkTarget}
              onDismiss={clearGenerationError}
            />
          )}

          {probeAt != null && currentRhizome && (
            <ProbePanel
              key={probeAt}
              rhizomeId={currentRhizome.rhizome_id}
              nodeId={probeAt}
              provider={branchDefaults.provider}
              model={branchDefaults.model}
              onClose={() => setProbeAt(null)}
            />
          )}

          {view.fork.forkTarget != null && !isGenerating && (
            <ForkPanelFor view={view} mode={view.fork.forkTarget.mode} />
          )}

          <div ref={bottomRef} />
        </div>
      </div>

      <div className="document-dock">
        {selected && (
          <div className="document-passage-bar">
            <div className="passage-bar-row">
              <span className="passage-who" title={whoWrote(selected)}>{whoWrote(selected)}</span>
              {selected.logprobs && isModel(selected) && (
                <span className="passage-certainty">
                  {(averageCertainty(selected.logprobs) * 100).toFixed(0)}%
                </span>
              )}
              {(childMap.get(selected.parent_id)?.length ?? 0) > 1 && (
                <BranchIndicator
                  node={selected}
                  siblings={childMap.get(selected.parent_id) ?? []}
                  onSelect={(id) => {
                    selectBranch(selected.parent_id ?? '', id)
                    setSelectedId(id)
                    setCut(null)
                  }}
                />
              )}
              <span className="passage-bar-spacer" />
              <button
                className="passage-close"
                onClick={() => {
                  setSelectedId(null)
                  setCut(null)
                }}
                aria-label="Deselect passage"
              >
                ×
              </button>
            </div>
            <div className="passage-bar-row passage-bar-actions">
              <button
                disabled={isGenerating}
                onClick={() => generateUnder(selected.parent_id ?? '', selected)}
                title="Generate another version of this passage"
              >
                Regenerate
              </button>
              <button
                disabled={isGenerating}
                onClick={() => view.fork.setForkTarget({ parentId: selected.parent_id ?? '', mode: 'regenerate' })}
                title="Regenerate with other settings: model, sampling, several at once"
              >
                With settings…
              </button>
              <button
                disabled={isGenerating}
                onClick={() => generateUnder(selected.node_id, selected)}
                title="Branch: generate what comes after this passage"
              >
                Continue from here
              </button>
              <button
                disabled={isGenerating}
                onClick={() => openSteer(selected.node_id)}
                title="Steer what comes after this passage, token by token"
              >
                Steer from here
              </button>
              <button
                disabled={isGenerating}
                onClick={() => setProbeAt(selected.node_id)}
                title="Sample what might come next here, grouped by what it says"
              >
                Probe what's next
              </button>
              {isModel(selected) && (
                <button
                  className={showDetails ? 'active' : undefined}
                  onClick={() => setShowDetails((d) => !d)}
                  title="What the model saw, and how it sampled"
                >
                  Details
                </button>
              )}
            </div>
            {cut?.nodeId === selected.node_id && currentRhizome ? (
              <TokenBranch
                key={cut.index}
                rhizomeId={currentRhizome.rhizome_id}
                node={selected}
                index={cut.index}
                onWrite={(at) => {
                  setWriteAfter(at)
                  setSelectedId(null)
                  setTimeout(() => composerRef.current?.focus(), 0)
                }}
                onClose={() => setCut(null)}
              />
            ) : tokenized(selected) && !isGenerating && (
              <div className="passage-hint">Click a token to branch before it.</div>
            )}
            {showDetails && isModel(selected) && (
              <div className="passage-details">
                <div className="passage-meta">
                  {[
                    selected.finish_reason && `ended: ${selected.finish_reason}`,
                    formatUsage(selected.usage),
                    ...formatSamplingMeta(selected.sampling_params),
                  ].filter(Boolean).join(' · ')}
                </div>
                {selected.prompt_text && (
                  <PromptTextViewer
                    promptText={selected.prompt_text}
                    inputTokens={selected.usage?.input_tokens}
                  />
                )}
              </div>
            )}
          </div>
        )}
        <DocumentComposer
          textareaRef={composerRef}
          isGenerating={isGenerating}
          atBranch={writeAfter != null && writeAfter !== leafNodeId}
          onCancelBranch={() => setWriteAfter(null)}
          onContinue={composer.continue}
          onAdd={composer.add}
          onSteer={composer.steer}
          onProbe={composer.probe}
          onStop={stopGeneration}
        />
      </div>

      <InspectedContext nodes={nodes} />
    </div>
  )
}

/**
 * Write the next part. What's typed is added exactly as written -- spaces
 * and line breaks included, since the model sees the text joined as-is.
 */
function DocumentComposer({
  textareaRef, isGenerating, atBranch, onCancelBranch, onContinue, onAdd, onSteer, onProbe, onStop,
}: {
  textareaRef: React.RefObject<HTMLTextAreaElement | null>
  isGenerating: boolean
  /** Writing at a branch point, not the end */
  atBranch: boolean
  onCancelBranch: () => void
  onContinue: (text: string) => void
  onAdd: (text: string) => void
  onSteer: (text: string) => void
  onProbe: (text: string) => void
  onStop: () => void
}) {
  const [text, setText] = useState('')

  // Whitespace alone never reaches the model (empty parts are skipped), so
  // it can't be a part of its own: it has to lead into some words
  const onlySpace = text.length > 0 && text.trim().length === 0

  const reset = () => {
    setText('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }

  const handleContinue = () => {
    if (isGenerating || onlySpace) return
    onContinue(text)
    reset()
  }

  const handleAdd = () => {
    if (isGenerating || !text || onlySpace) return
    onAdd(text)
    reset()
  }

  const handleProbe = () => {
    if (isGenerating || onlySpace) return
    onProbe(text)
    reset()
  }

  const handleSteer = () => {
    if (isGenerating || onlySpace) return
    onSteer(text)
    reset()
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter is a line break here; Cmd/Ctrl+Enter continues, with Shift adds only
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      if (e.shiftKey) handleAdd()
      else handleContinue()
    } else if (e.key === 'Escape' && atBranch) {
      onCancelBranch()
    }
  }

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setText(e.target.value)
    const el = e.target
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 240)}px`
  }

  return (
    <div className="message-input document-composer">
      {atBranch && (
        <div className="document-composer-branch">
          Writing a new branch here, in place of what followed
          <button onClick={onCancelBranch} aria-label="Back to the end">×</button>
        </div>
      )}
      <div className="message-input-inner">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder={isGenerating ? 'Generating...' : 'Write what comes next...'}
          disabled={isGenerating}
          rows={1}
        />
        {isGenerating ? (
          <button onClick={onStop}>Stop</button>
        ) : (
          <button
            onClick={handleContinue}
            disabled={onlySpace}
            title={text ? 'Add this and let the model continue (Cmd+Enter)' : 'Let the model continue (Cmd+Enter)'}
          >
            Continue
          </button>
        )}
        <button
          className="send-only-btn"
          onClick={handleAdd}
          disabled={isGenerating || !text || onlySpace}
          title="Add without generating (Shift+Cmd+Enter)"
        >
          Add only
        </button>
        <button
          className="send-only-btn"
          onClick={handleSteer}
          disabled={isGenerating || onlySpace}
          title="Steer what comes next, token by token (local models)"
        >
          Steer
        </button>
        <button
          className="send-only-btn"
          onClick={handleProbe}
          disabled={isGenerating}
          title="Sample what might come next, grouped by what it says"
        >
          Probe
        </button>
      </div>
      {onlySpace && (
        <div className="document-composer-hint">
          Spaces or line breaks alone aren't sent to the model; keep writing after them.
        </div>
      )}
    </div>
  )
}
