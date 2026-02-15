import type { NodeResponse } from '../../api/types.ts'
import { BranchIndicator } from './BranchIndicator.tsx'
import { ContextBar } from './ContextBar.tsx'
import './MessageRow.css'

interface MessageRowProps {
  node: NodeResponse
  siblings: NodeResponse[]
  onSelectSibling: (siblingId: string) => void
  onFork: () => void
}

export function MessageRow({ node, siblings, onSelectSibling, onFork }: MessageRowProps) {
  return (
    <div className={`message-row ${node.role}`}>
      <div className="message-header">
        <div className="message-role">{node.role}</div>
        {node.sibling_count > 1 && (
          <BranchIndicator
            node={node}
            siblings={siblings}
            onSelect={onSelectSibling}
          />
        )}
        <button className="fork-btn" onClick={onFork}>
          {node.role === 'assistant' ? 'Regen' : 'Fork'}
        </button>
      </div>
      <div className="message-content">{node.content}</div>
      {node.role === 'assistant' && node.context_usage != null && (
        <ContextBar contextUsage={node.context_usage} />
      )}
      {node.latency_ms != null && (
        <div className="message-meta">
          {node.latency_ms}ms
          {node.usage && ` \u00b7 ${node.usage.input_tokens}+${node.usage.output_tokens} tokens`}
        </div>
      )}
    </div>
  )
}
