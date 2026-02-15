import { useEffect, useRef } from 'react'
import type { NodeResponse } from '../../api/types.ts'
import { useTreeStore } from '../../store/treeStore.ts'
import './LinearView.css'

/**
 * Walk the parent chain from root to leaf to get nodes in conversation order.
 * For a linear conversation, this is straightforward. For branching trees,
 * we follow the path to the most recent leaf.
 */
function getLinearPath(nodes: NodeResponse[]): NodeResponse[] {
  if (nodes.length === 0) return []

  const childMap = new Map<string | null, NodeResponse[]>()
  for (const node of nodes) {
    const children = childMap.get(node.parent_id) ?? []
    children.push(node)
    childMap.set(node.parent_id, children)
  }

  // Walk from root, always picking the last child (most recent)
  const path: NodeResponse[] = []
  let currentChildren = childMap.get(null) ?? []

  while (currentChildren.length > 0) {
    const node = currentChildren[currentChildren.length - 1]
    path.push(node)
    currentChildren = childMap.get(node.node_id) ?? []
  }

  return path
}

export function LinearView() {
  const { currentTree, isGenerating, streamingContent } = useTreeStore()
  const bottomRef = useRef<HTMLDivElement>(null)

  const nodes = currentTree?.nodes ?? []
  const path = getLinearPath(nodes)

  // Auto-scroll on new content
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [path.length, streamingContent])

  if (!currentTree) return null

  return (
    <div className="linear-view">
      <div className="messages">
        {path.map((node) => (
          <MessageRow key={node.node_id} node={node} />
        ))}

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

function MessageRow({ node }: { node: NodeResponse }) {
  return (
    <div className={`message-row ${node.role}`}>
      <div className="message-role">{node.role}</div>
      <div className="message-content">{node.content}</div>
      {node.latency_ms != null && (
        <div className="message-meta">
          {node.latency_ms}ms
          {node.usage && ` · ${node.usage.input_tokens}+${node.usage.output_tokens} tokens`}
        </div>
      )}
    </div>
  )
}
