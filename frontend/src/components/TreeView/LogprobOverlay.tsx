import { useState } from 'react'
import type { LogprobData, TokenLogprob } from '../../api/types.ts'
import './LogprobOverlay.css'

interface LogprobOverlayProps {
  logprobs: LogprobData
}

/**
 * Maps linear probability to an HSLA background color.
 * High confidence (>0.95) is transparent — no visual noise.
 * Low confidence gets a warm highlight anchored to sienna (~20 hue).
 */
function uncertaintyColor(linearProb: number): string {
  if (linearProb >= 0.95) return 'transparent'

  // Uncertainty as 0..1 scale (inverted from probability)
  const u = 1 - linearProb

  // Non-linear ramp: sqrt pushes faint highlights further into the visible range
  const intensity = Math.sqrt(u)

  // Warm sienna hue (~20), saturation scales with uncertainty
  const saturation = 40 + intensity * 50 // 40% → 90%
  const lightness = 55 - intensity * 10 // 55% → 45%
  const alpha = intensity * 0.45 // 0 → 0.45

  return `hsla(20, ${saturation}%, ${lightness}%, ${alpha})`
}

function formatProb(linearProb: number): string {
  return `${(linearProb * 100).toFixed(1)}%`
}

function TokenTooltip({ token }: { token: TokenLogprob }) {
  return (
    <div className="token-tooltip">
      <div className="token-tooltip-chosen">
        <span className="token-tooltip-token">{JSON.stringify(token.token)}</span>
        <span className="token-tooltip-prob">{formatProb(token.linear_prob)}</span>
      </div>
      {token.top_alternatives.length > 0 && (
        <div className="token-tooltip-alts">
          {token.top_alternatives.map((alt, i) => (
            <div key={i} className="token-tooltip-alt">
              <span className="token-tooltip-token">{JSON.stringify(alt.token)}</span>
              <span className="token-tooltip-prob">{formatProb(alt.linear_prob)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function LogprobOverlay({ logprobs }: LogprobOverlayProps) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null)

  return (
    <span className="logprob-overlay">
      {logprobs.tokens.map((token, i) => (
        <span
          key={i}
          className="logprob-token"
          style={{ backgroundColor: uncertaintyColor(token.linear_prob) }}
          onMouseEnter={() => setHoveredIndex(i)}
          onMouseLeave={() => setHoveredIndex(null)}
        >
          {token.token}
          {hoveredIndex === i && <TokenTooltip token={token} />}
        </span>
      ))}
    </span>
  )
}

export function averageCertainty(logprobs: LogprobData): number {
  if (logprobs.tokens.length === 0) return 1
  const sum = logprobs.tokens.reduce((acc, t) => acc + t.linear_prob, 0)
  return sum / logprobs.tokens.length
}

export { uncertaintyColor }
