import { useState } from 'react'
import type { LogprobData, NodeResponse, SamplingParams, TokenLogprob } from '../../api/types.ts'
import { useRhizomeStore } from '../../store/rhizomeStore.ts'
import { LogprobOverlay, averageCertainty, uncertaintyColor } from '../RhizomeView/LogprobOverlay.tsx'
import { ThinkingSection } from '../RhizomeView/ThinkingSection.tsx'
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

const HISTOGRAM_BINS = 10

function buildHistogram(logprobs: LogprobData): number[] {
  const bins = new Array(HISTOGRAM_BINS).fill(0)
  for (const token of logprobs.tokens) {
    const bin = Math.min(Math.floor(token.linear_prob * HISTOGRAM_BINS), HISTOGRAM_BINS - 1)
    bins[bin]++
  }
  return bins
}

function findMinCertaintyToken(logprobs: LogprobData): TokenLogprob | null {
  if (logprobs.tokens.length === 0) return null
  let min = logprobs.tokens[0]
  for (const t of logprobs.tokens) {
    if (t.linear_prob < min.linear_prob) min = t
  }
  return min
}

function CertaintyHistogram({ logprobs }: { logprobs: LogprobData }) {
  const bins = buildHistogram(logprobs)
  const max = Math.max(...bins, 1)

  return (
    <div className="certainty-histogram" title="Token probability distribution (0-100%)">
      {bins.map((count, i) => (
        <div
          key={i}
          className="certainty-histogram-bar"
          style={{
            height: `${(count / max) * 100}%`,
            backgroundColor: uncertaintyColor(i / HISTOGRAM_BINS) === 'transparent'
              ? 'var(--accent)'
              : uncertaintyColor(i / HISTOGRAM_BINS),
            opacity: count === 0 ? 0.15 : 1,
          }}
        />
      ))}
    </div>
  )
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
  const setComparisonHoveredNodeId = useRhizomeStore((s) => s.setComparisonHoveredNodeId)
  const [showLogprobs, setShowLogprobs] = useState(false)
  const logprobs = node.logprobs
  const avgCertainty = logprobs ? averageCertainty(logprobs) : null
  const minToken = logprobs ? findMinCertaintyToken(logprobs) : null

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
        {showLogprobs && logprobs ? (
          <LogprobOverlay logprobs={logprobs} />
        ) : diffSegments ? (
          <DiffContent segments={diffSegments} />
        ) : (
          node.content
        )}
      </div>

      {logprobs && (
        <div className="comparison-card-certainty">
          <CertaintyHistogram logprobs={logprobs} />
          <div className="comparison-card-certainty-stats">
            {avgCertainty != null && (
              <span
                className="comparison-certainty"
                style={{
                  color: uncertaintyColor(avgCertainty) === 'transparent'
                    ? 'var(--ctx-green)'
                    : uncertaintyColor(avgCertainty),
                }}
              >
                avg {(avgCertainty * 100).toFixed(0)}%
              </span>
            )}
            {minToken && (
              <span className="comparison-min-token" title={`Least confident: "${minToken.token}"`}>
                min{' '}
                <span style={{
                  color: uncertaintyColor(minToken.linear_prob) === 'transparent'
                    ? 'var(--ctx-green)'
                    : uncertaintyColor(minToken.linear_prob),
                  fontWeight: 600,
                }}>
                  {(minToken.linear_prob * 100).toFixed(0)}%
                </span>
                {' '}
                <span className="comparison-min-token-preview">
                  {JSON.stringify(minToken.token)}
                </span>
              </span>
            )}
            <button
              className={`comparison-logprob-toggle${showLogprobs ? ' active' : ''}`}
              onClick={(e) => { e.stopPropagation(); setShowLogprobs(!showLogprobs) }}
              title={showLogprobs ? 'Hide token confidence' : 'Show token confidence'}
            >
              {showLogprobs ? 'hide overlay' : 'show overlay'}
            </button>
          </div>
        </div>
      )}

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
        {!logprobs && avgCertainty != null && (
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
