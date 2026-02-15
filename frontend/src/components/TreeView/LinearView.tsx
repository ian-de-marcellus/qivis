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
    isGenerating,
    streamingContent,
    regeneratingParentId,
    branchSelections,
    selectBranch,
    forkAndGenerate,
    regenerate,
  } = useTreeStore()

  const bottomRef = useRef<HTMLDivElement>(null)
  const [forkTarget, setForkTarget] = useState<ForkTarget | null>(null)

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
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [path.length, streamingContent])

  if (!currentTree) return null

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
                  defaults={{
                    provider: currentTree.default_provider,
                    model: currentTree.default_model,
                    systemPrompt: currentTree.default_system_prompt,
                  }}
                />
              )}
            </Fragment>
          )
        })}

        {isGenerating && streamingContent && (
          <div className="message-row assistant">
            <div className="message-role">assistant</div>
            <div className="message-content">
              {streamingContent}
              <span className="streaming-cursor" />
            </div>
          </div>
        )}

        {isGenerating && !streamingContent && (
          <div className="message-row assistant">
            <div className="message-role">assistant</div>
            <div className="message-content thinking">Thinking...</div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  )
}
