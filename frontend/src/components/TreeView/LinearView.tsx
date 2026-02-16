import { Fragment, useEffect, useRef, useState } from 'react'
import type { GenerateRequest, NodeResponse } from '../../api/types.ts'
import { getActivePath, useTreeStore } from '../../store/treeStore.ts'
import { ForkPanel } from './ForkPanel.tsx'
import { MessageRow } from './MessageRow.tsx'
import './LinearView.css'

interface ForkTarget {
  parentId: string
  mode: 'fork' | 'regenerate'
}

export function LinearView() {
  const {
    currentTree,
    providers,
    isGenerating,
    streamingContent,
    streamingContents,
    streamingNodeIds,
    streamingTotal,
    activeStreamIndex,
    regeneratingParentId,
    generationError,
    branchSelections,
    selectBranch,
    setActiveStreamIndex,
    forkAndGenerate,
    regenerate,
    clearGenerationError,
    fetchProviders,
  } = useTreeStore()

  const bottomRef = useRef<HTMLDivElement>(null)
  const [forkTarget, setForkTarget] = useState<ForkTarget | null>(null)

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
  }, [path.length, streamingContent, activeMultiContent])

  if (!currentTree) return null

  const leafNodeId = path.length > 0 ? path[path.length - 1].node_id : null

  // Branch-local defaults: use last assistant node's provider/model from active path
  const lastAssistant = [...path].reverse().find((n) => n.role === 'assistant')
  const branchDefaults = {
    provider: lastAssistant?.provider ?? currentTree.default_provider,
    model: lastAssistant?.model ?? currentTree.default_model,
    systemPrompt: currentTree.default_system_prompt,
  }

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
              />
              {!isGenerating && forkTarget?.parentId === nodeParentKey && (
                <ForkPanel
                  mode={forkTarget.mode}
                  onForkSubmit={handleForkSubmit}
                  onRegenerateSubmit={handleRegenerateSubmit}
                  onCancel={() => setForkTarget(null)}
                  isGenerating={isGenerating}
                  providers={providers}
                  defaults={branchDefaults}
                  streamDefault={currentTree.metadata?.stream_responses !== false}
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
                : <span className="thinking">Thinking...</span>
              }
            </div>
          </div>
        )}

        {isGenerating && streamingTotal <= 1 && streamingContent && (
          <div className="message-row assistant">
            <div className="message-role">assistant</div>
            <div className="message-content">
              {streamingContent}
              <span className="streaming-cursor" />
            </div>
          </div>
        )}

        {isGenerating && streamingTotal <= 1 && !streamingContent && (
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
    </div>
  )
}
