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
  const roleLabel = node.role === 'researcher_note'
    ? 'Researcher Note'
    : node.role.charAt(0).toUpperCase() + node.role.slice(1)

  return (
    <div className={`message-row ${node.role}`}>
      <div className="message-header">
        <span className="message-role">{roleLabel}</span>
        {node.role === 'assistant' && node.model && (
          <span className="message-model">{node.model}</span>
        )}
        {node.sibling_count > 1 && (
          <BranchIndicator
            node={node}
            siblings={siblings}
            onSelect={onSelectSibling}
          />
        )}
        <button className="fork-btn" onClick={onFork} aria-label={node.role === 'assistant' ? 'Regenerate' : 'Fork'}>
          {node.role === 'assistant' ? 'Regen' : 'Fork'}
        </button>
      </div>
      <div className="message-content">{node.content}</div>
      {node.role === 'assistant' && node.context_usage != null && (
        <ContextBar contextUsage={node.context_usage} />
      )}
      {node.latency_ms != null && (
        <div className="message-meta">
          {(node.latency_ms / 1000).toFixed(1)}s
          {node.usage && ` \u00b7 ${node.usage.input_tokens.toLocaleString()}+${node.usage.output_tokens.toLocaleString()} tok`}
        </div>
      )}
    </div>
  )
}
