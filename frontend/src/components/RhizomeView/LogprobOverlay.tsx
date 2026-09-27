import { useState } from 'react'
import type { LogprobData, TokenLogprob } from '../../api/types.ts'
import { uncertaintyColor } from './logprobColor.ts'
import './LogprobOverlay.css'

interface LogprobOverlayProps {
  logprobs: LogprobData
}


function formatProb(linearProb: number): string {
  return `${(linearProb * 100).toFixed(1)}%`
}

function TokenTooltip({ token }: { token: TokenLogprob }) {
  const altCount = token.top_alternatives.length
  const isLargeSet = altCount > 10

  return (
    <div className={`token-tooltip${isLargeSet ? ' token-tooltip-scrollable' : ''}`}>
      <div className="token-tooltip-chosen">
        <span className="token-tooltip-token">{JSON.stringify(token.token)}</span>
        <span className="token-tooltip-prob">{formatProb(token.linear_prob)}</span>
      </div>
      {altCount > 0 && (
        <>
          {isLargeSet && (
            <div className="token-tooltip-count">{altCount} alternatives</div>
          )}
          <div className={`token-tooltip-alts${isLargeSet ? ' token-tooltip-alts-scroll' : ''}`}>
            {token.top_alternatives.map((alt, i) => (
              <div key={i} className="token-tooltip-alt">
                <span className="token-tooltip-token">{JSON.stringify(alt.token)}</span>
                <span className="token-tooltip-prob">{formatProb(alt.linear_prob)}</span>
              </div>
            ))}
          </div>
        </>
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
