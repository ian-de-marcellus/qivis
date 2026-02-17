import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import type { GenerateRequest, NodeResponse } from '../../api/types.ts'
import { getActivePath, useTreeStore } from '../../store/treeStore.ts'
import { ComparisonView } from '../ComparisonView/ComparisonView.tsx'
import { ContextModal } from './ContextModal.tsx'
import { ContextSplitView } from './ContextSplitView.tsx'
import { reconstructContext } from './contextReconstruction.ts'
import { computeDiffSummary, buildDiffRows, getTreeDefaults } from './contextDiffs.ts'
import type { DiffSummary } from './contextDiffs.ts'
import { ForkPanel } from './ForkPanel.tsx'
import { MessageRow } from './MessageRow.tsx'
import { ThinkingSection } from './ThinkingSection.tsx'
import './LinearView.css'

interface ForkTarget {
  parentId: string
  mode: 'fork' | 'regenerate' | 'prefill' | 'generate'
}

export function LinearView() {
  const {
    currentTree,
    providers,
    isGenerating,
    streamingContent,
    streamingThinkingContent,
    streamingContents,
    streamingThinkingContents,
    streamingNodeIds,
    streamingTotal,
    activeStreamIndex,
    regeneratingParentId,
    generationError,
    branchSelections,
    selectBranch,
    editNodeContent,
    setActiveStreamIndex,
    forkAndGenerate,
    regenerate,
    prefillAssistant,
    clearGenerationError,
    fetchProviders,
    selectedEditVersion,
    editHistoryCache,
    inspectedNodeId,
    setInspectedNodeId,
    splitViewNodeId,
    setSplitViewNodeId,
  } = useTreeStore()

  const bottomRef = useRef<HTMLDivElement>(null)
  const [forkTarget, setForkTarget] = useState<ForkTarget | null>(null)
  const [comparingAtParent, setComparingAtParent] = useState<string | null>(null)

  // Fetch providers once on mount
  useEffect(() => {
    fetchProviders()
  }, [fetchProviders])

  const nodes = currentTree?.nodes ?? []
  let path = getActivePath(nodes, branchSelections)

  // Build childMap for sibling lookups
  const childMap = new Map<string | null, NodeResponse[]>()
  for (const node of nodes) {
    const children = childMap.get(node.parent_id) ?? []
    children.push(node)
    childMap.set(node.parent_id, children)
  }

  // When regenerating, truncate the path at the regeneration point
  // so the old assistant message (and everything below it) disappears
  if (regeneratingParentId != null) {
    const cutIndex = path.findIndex((n) => n.parent_id === regeneratingParentId)
    if (cutIndex !== -1) {
      path = path.slice(0, cutIndex)
    }
  }

  // Auto-scroll on new content
  const activeMultiContent = streamingContents[activeStreamIndex]
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [path.length, streamingContent, streamingThinkingContent, activeMultiContent])

  if (!currentTree) return null

  const leafNodeId = path.length > 0 ? path[path.length - 1].node_id : null

  // Branch-local defaults: use last assistant node's provider/model from active path
  const lastAssistant = [...path].reverse().find((n) => n.role === 'assistant')
  const branchDefaults = {
    provider: lastAssistant?.provider ?? currentTree.default_provider,
    model: lastAssistant?.model ?? currentTree.default_model,
    systemPrompt: currentTree.default_system_prompt,
  }

  // Compute highlight classes when an edit version is selected
  const highlights = useMemo(() => {
    const map = new Map<string, 'highlight-used' | 'highlight-other'>()
    if (!selectedEditVersion) return map

    const { nodeId, entry } = selectedEditVersion
    const editedNodeIdx = path.findIndex((n) => n.node_id === nodeId)
    if (editedNodeIdx === -1) return map

    // Determine the time window for this version
    const cachedEntries = editHistoryCache[nodeId]
    if (!cachedEntries && entry !== null) return map // history not loaded yet for non-original

    const editedNode = path[editedNodeIdx]

    let windowStart: string
    let windowEnd: string | null = null

    if (entry === null) {
      // "Original" pseudo-entry — active from node creation until first edit
      windowStart = editedNode.created_at
      if (cachedEntries && cachedEntries.length > 0) {
        windowEnd = cachedEntries[0].timestamp
      }
    } else {
      // Specific edit entry — find its position in the ordered list
      windowStart = entry.timestamp
      if (cachedEntries) {
        const entryIdx = cachedEntries.findIndex((e) => e.event_id === entry.event_id)
        if (entryIdx !== -1 && entryIdx < cachedEntries.length - 1) {
          windowEnd = cachedEntries[entryIdx + 1].timestamp
        }
      }
    }

    // Walk all assistant nodes after the edited node in the path
    for (let i = editedNodeIdx + 1; i < path.length; i++) {
      const n = path[i]
      if (n.role !== 'assistant') continue

      const nodeTime = n.created_at
      const inWindow = nodeTime >= windowStart && (windowEnd === null || nodeTime < windowEnd)
      map.set(n.node_id, inWindow ? 'highlight-used' : 'highlight-other')
    }

    return map
  }, [selectedEditVersion, path, editHistoryCache])

  // Compute diff summaries for assistant nodes (for diff badges)
  const diffSummaries = useMemo(() => {
    const map = new Map<string, DiffSummary>()
    if (!currentTree) return map
    const treeDefaults = getTreeDefaults(currentTree)
    for (const node of path) {
      if (node.role === 'assistant' && node.mode !== 'manual') {
        map.set(node.node_id, computeDiffSummary(node, path, treeDefaults))
      }
    }
    return map
  }, [currentTree, path])

  const handleSelectSibling = (parentId: string, siblingId: string) => {
    selectBranch(parentId, siblingId)
  }

  const handleFork = (parentId: string, role: string) => {
    const mode = role === 'assistant' ? 'regenerate' : 'fork'
    if (forkTarget?.parentId === parentId && forkTarget.mode === mode) {
      setForkTarget(null)
    } else {
      setForkTarget({ parentId, mode })
    }
  }

  const handleForkSubmit = (content: string, overrides: GenerateRequest) => {
    if (forkTarget != null) {
      forkAndGenerate(forkTarget.parentId, content, overrides)
      setForkTarget(null)
    }
  }

  const handleRegenerateSubmit = (overrides: GenerateRequest) => {
    if (forkTarget != null) {
      regenerate(forkTarget.parentId, overrides)
      setForkTarget(null)
    }
  }

  const handlePrefillSubmit = (content: string) => {
    if (forkTarget != null) {
      prefillAssistant(forkTarget.parentId, content)
      setForkTarget(null)
    }
  }

  return (
    <div className="linear-view">
      <div className="messages">
        {path.map((node) => {
          const siblings = childMap.get(node.parent_id) ?? []
          const nodeParentKey = node.parent_id ?? ''

          return (
            <Fragment key={node.node_id}>
              <MessageRow
                node={node}
                siblings={siblings}
                onSelectSibling={(siblingId) =>
                  handleSelectSibling(nodeParentKey, siblingId)
                }
                onFork={() => handleFork(nodeParentKey, node.role)}
                onPrefill={node.role === 'user' ? () => {
                  if (forkTarget?.parentId === node.node_id && forkTarget.mode === 'prefill') {
                    setForkTarget(null)
                  } else {
                    setForkTarget({ parentId: node.node_id, mode: 'prefill' })
                  }
                } : undefined}
                onGenerate={node.role === 'user' ? () => {
                  if (forkTarget?.parentId === node.node_id && forkTarget.mode === 'generate') {
                    setForkTarget(null)
                  } else {
                    setForkTarget({ parentId: node.node_id, mode: 'generate' })
                  }
                } : undefined}
                onEdit={(nodeId, editedContent) => editNodeContent(nodeId, editedContent)}
                onInspect={node.role === 'assistant' && node.mode !== 'manual'
                  ? () => setInspectedNodeId(
                      inspectedNodeId === node.node_id ? null : node.node_id
                    )
                  : undefined}
                diffSummary={diffSummaries.get(node.node_id)}
                onSplitView={diffSummaries.has(node.node_id)
                  ? () => setSplitViewNodeId(
                      splitViewNodeId === node.node_id ? null : node.node_id
                    )
                  : undefined}
                onCompare={siblings.length > 1 ? () => setComparingAtParent(
                  comparingAtParent === nodeParentKey ? null : nodeParentKey,
                ) : undefined}
                highlightClass={highlights.get(node.node_id)}
              />
              {comparingAtParent === nodeParentKey && (
                <ComparisonView
                  siblings={siblings}
                  selectedNodeId={node.node_id}
                  onSelect={(selectedId) => {
                    selectBranch(nodeParentKey, selectedId)
                    setComparingAtParent(null)
                  }}
                  onDismiss={() => setComparingAtParent(null)}
                />
              )}
              {!isGenerating && forkTarget != null && (
                forkTarget.mode === 'prefill' || forkTarget.mode === 'generate'
                  ? forkTarget.parentId === node.node_id
                  : forkTarget.parentId === nodeParentKey
              ) && (
                <ForkPanel
                  mode={forkTarget.mode}
                  onForkSubmit={handleForkSubmit}
                  onRegenerateSubmit={handleRegenerateSubmit}
                  onPrefillSubmit={handlePrefillSubmit}
                  onCancel={() => setForkTarget(null)}
                  isGenerating={isGenerating}
                  providers={providers}
                  defaults={branchDefaults}
                  streamDefault={currentTree.metadata?.stream_responses !== false}
                  samplingDefaults={currentTree.default_sampling_params}
                />
              )}
            </Fragment>
          )
        })}

        {isGenerating && streamingTotal > 1 && (
          <div className="message-row assistant">
            <div className="message-header-row">
              <div className="message-role">assistant</div>
              <div className="streaming-branch-nav">
                <button
                  className="streaming-nav-arrow"
                  onClick={() => setActiveStreamIndex(activeStreamIndex - 1)}
                  disabled={activeStreamIndex <= 0}
                >
                  &#8249;
                </button>
                <span className="streaming-nav-label">
                  {activeStreamIndex + 1} of {streamingTotal}
                </span>
                <button
                  className="streaming-nav-arrow"
                  onClick={() => setActiveStreamIndex(activeStreamIndex + 1)}
                  disabled={activeStreamIndex >= streamingTotal - 1}
                >
                  &#8250;
                </button>
              </div>
            </div>
            {streamingThinkingContents[activeStreamIndex] && (
              <ThinkingSection
                thinkingContent={streamingThinkingContents[activeStreamIndex]}
                isStreaming={!streamingContents[activeStreamIndex]}
              />
            )}
            <div className="message-content">
              {streamingContents[activeStreamIndex]
                ? (
                  <>
                    {streamingContents[activeStreamIndex]}
                    {!streamingNodeIds[activeStreamIndex] && (
                      <span className="streaming-cursor" />
                    )}
                  </>
                )
                : streamingThinkingContents[activeStreamIndex]
                  ? null
                  : <span className="thinking">Thinking...</span>
              }
            </div>
          </div>
        )}

        {isGenerating && streamingTotal <= 1 && (streamingContent || streamingThinkingContent) && (
          <div className="message-row assistant">
            <div className="message-role">assistant</div>
            {streamingThinkingContent && (
              <ThinkingSection
                thinkingContent={streamingThinkingContent}
                isStreaming={!streamingContent}
              />
            )}
            <div className="message-content">
              {streamingContent
                ? (
                  <>
                    {streamingContent}
                    <span className="streaming-cursor" />
                  </>
                )
                : streamingThinkingContent
                  ? null
                  : <span className="thinking">Thinking...</span>
              }
            </div>
          </div>
        )}

        {isGenerating && streamingTotal <= 1 && !streamingContent && !streamingThinkingContent && (
          <div className="message-row assistant">
            <div className="message-role">assistant</div>
            <div className="message-content thinking">Thinking...</div>
          </div>
        )}

        {!isGenerating && generationError && leafNodeId === generationError.parentNodeId && (
          <div className="generation-error-panel">
            <div className="generation-error-header">Generation failed</div>
            <div className="generation-error-message">{generationError.errorMessage}</div>
            <div className="generation-error-actions">
              <button
                className="generation-error-retry"
                onClick={() => {
                  regenerate(generationError.parentNodeId, {
                    provider: generationError.provider,
                    model: generationError.model ?? undefined,
                    system_prompt: generationError.systemPrompt ?? undefined,
                  })
                }}
              >
                Retry
              </button>
              <button
                className="generation-error-settings"
                onClick={() => {
                  clearGenerationError()
                  setForkTarget({ parentId: generationError.parentNodeId, mode: 'regenerate' })
                }}
              >
                Change settings
              </button>
              <button className="generation-error-dismiss" onClick={clearGenerationError}>
                Dismiss
              </button>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {inspectedNodeId && (() => {
        const inspectedNode = nodes.find((n) => n.node_id === inspectedNodeId)
        if (!inspectedNode) return null
        return (
          <ContextModal
            context={reconstructContext(inspectedNode, nodes)}
            onDismiss={() => setInspectedNodeId(null)}
          />
        )
      })()}

      {splitViewNodeId && currentTree && (() => {
        const splitNode = nodes.find((n) => n.node_id === splitViewNodeId)
        if (!splitNode) return null
        const treeDefaults = getTreeDefaults(currentTree)
        return (
          <ContextSplitView
            rows={buildDiffRows(splitNode, nodes, treeDefaults)}
            summary={computeDiffSummary(splitNode, path, treeDefaults)}
            context={reconstructContext(splitNode, nodes)}
            responseContent={splitNode.content}
            onDismiss={() => setSplitViewNodeId(null)}
          />
        )
      })()}
    </div>
  )
}
