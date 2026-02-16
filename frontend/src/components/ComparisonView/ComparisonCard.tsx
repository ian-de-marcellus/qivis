import type { NodeResponse, SamplingParams } from '../../api/types.ts'
import { useTreeStore } from '../../store/treeStore.ts'
import { averageCertainty, uncertaintyColor } from '../TreeView/LogprobOverlay.tsx'
import { ThinkingSection } from '../TreeView/ThinkingSection.tsx'
import type { DiffSegment } from './wordDiff.ts'

interface ComparisonCardProps {
  node: NodeResponse
  isSelected: boolean
  diffSegments?: DiffSegment[]
  onSelect: (nodeId: string) => void
}

function formatSamplingMeta(sp: SamplingParams | null | undefined): string[] {
  if (!sp) return []
  const parts: string[] = []
  if (sp.temperature != null) parts.push(`temp ${sp.temperature}`)
  if (sp.top_p != null) parts.push(`top_p ${sp.top_p}`)
  if (sp.top_k != null) parts.push(`top_k ${sp.top_k}`)
  if (sp.max_tokens != null && sp.max_tokens !== 2048) parts.push(`max_tok ${sp.max_tokens}`)
  if (sp.frequency_penalty != null) parts.push(`freq_pen ${sp.frequency_penalty}`)
  if (sp.presence_penalty != null) parts.push(`pres_pen ${sp.presence_penalty}`)
  if (sp.extended_thinking) parts.push('thinking')
  return parts
}

function DiffContent({ segments }: { segments: DiffSegment[] }) {
  return (
    <>
      {segments.map((seg, i) => {
        if (seg.type === 'common') return <span key={i}>{seg.text}</span>
        if (seg.type === 'added') return <span key={i} className="diff-added">{seg.text}</span>
        return <span key={i} className="diff-removed">{seg.text}</span>
      })}
    </>
  )
}

export function ComparisonCard({ node, isSelected, diffSegments, onSelect }: ComparisonCardProps) {
  const setComparisonHoveredNodeId = useTreeStore((s) => s.setComparisonHoveredNodeId)
  const logprobs = node.logprobs
  const avgCertainty = logprobs ? averageCertainty(logprobs) : null

  const roleLabel = node.role === 'researcher_note'
    ? 'Note'
    : node.role.charAt(0).toUpperCase() + node.role.slice(1)

  return (
    <div
      className={`comparison-card${isSelected ? ' selected' : ''}`}
      onClick={() => onSelect(node.node_id)}
      onMouseEnter={() => setComparisonHoveredNodeId(node.node_id)}
      onMouseLeave={() => setComparisonHoveredNodeId(null)}
    >
      <div className="comparison-card-header">
        <span className="comparison-card-role">{roleLabel}</span>
        {node.model && (
          <span className="comparison-card-model">{node.model}</span>
        )}
        {isSelected && <span className="comparison-card-badge">current</span>}
      </div>

      {node.thinking_content && (
        <ThinkingSection thinkingContent={node.thinking_content} />
      )}

      <div className="comparison-card-content">
        {diffSegments ? (
          <DiffContent segments={diffSegments} />
        ) : (
          node.content
        )}
      </div>

      <div className="comparison-card-meta">
        {node.latency_ms != null && (
          <span>{(node.latency_ms / 1000).toFixed(1)}s</span>
        )}
        {node.usage && (
          <span>
            {node.latency_ms != null && ' \u00b7 '}
            {node.usage.input_tokens.toLocaleString()}+{node.usage.output_tokens.toLocaleString()} tok
          </span>
        )}
        {avgCertainty != null && (
          <span>
            {(node.latency_ms != null || node.usage) && ' \u00b7 '}
            <span
              className="comparison-certainty"
              style={{
                color: uncertaintyColor(avgCertainty) === 'transparent'
                  ? 'var(--ctx-green)'
                  : uncertaintyColor(avgCertainty),
              }}
            >
              {(avgCertainty * 100).toFixed(0)}%
            </span>
          </span>
        )}
        {formatSamplingMeta(node.sampling_params).map((label) => (
          <span key={label}>{` \u00b7 ${label}`}</span>
        ))}
      </div>
    </div>
  )
}
