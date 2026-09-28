import { useState } from 'react'
import type { LogprobData, TokenLogprob } from '../../api/types.ts'
import { uncertaintyColor } from './logprobColor.ts'
import { textTokenCount, textTokenOverflow } from './nodeFormat.ts'
import './LogprobOverlay.css'

interface LogprobOverlayProps {
  logprobs: LogprobData
  /** The reply's saved text: tokens beyond it show as one end-of-turn mark */
  content?: string
  /** No probability colors (the tokens stay hoverable and clickable) */
  plain?: boolean
  /** Makes tokens clickable, e.g. to branch before one */
  onTokenClick?: (index: number) => void
  /** Tokens from here on are shown as cut away */
  cutAt?: number | null
}


/** A template token like <|eot_id|>: recorded (it was a choice), shown as a quiet marker */
const isSpecial = (token: string) => /^<\|[^|<>]+\|>$/.test(token)

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
      {token.chosen_by && (
        <div className="token-tooltip-count">
          {token.chosen_by === 'researcher' ? 'steered by the researcher' : 'flowed through (the model\'s choice)'}
        </div>
      )}
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

export function LogprobOverlay({ logprobs, content, plain, onTokenClick, cutAt }: LogprobOverlayProps) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null)
  const tokens = logprobs.tokens
  const shown = content != null ? textTokenCount(tokens, content) : tokens.length
  // The part of the last shown token past the text belongs to the end mark
  const overflow = content != null ? textTokenOverflow(tokens, content) : 0
  // The space a word carries after "Sun:" isn't part of the saved turn
  const trimFirst = content != null && !/^\s/.test(content)
  const visible = (text: string, i: number) => {
    let t = i === 0 && trimFirst ? text.trimStart() : text
    if (i === shown - 1 && overflow > 0) t = t.slice(0, Math.max(0, t.length - overflow))
    return t
  }

  return (
    <span className="logprob-overlay">
      {tokens.slice(0, shown).map((token, i) => (
        <span
          key={i}
          className={[
            'logprob-token',
            token.chosen_by === 'researcher' && 'logprob-token-steered',
            onTokenClick && 'logprob-token-clickable',
            cutAt != null && i >= cutAt && 'logprob-token-cut',
            cutAt === i && 'logprob-token-cut-first',
          ].filter(Boolean).join(' ')}
          style={plain ? undefined : { backgroundColor: uncertaintyColor(token.linear_prob) }}
          onMouseEnter={() => setHoveredIndex(i)}
          onMouseLeave={() => setHoveredIndex(null)}
          onClick={onTokenClick && ((e) => {
            e.stopPropagation()
            onTokenClick(i)
          })}
        >
          {isSpecial(token.token)
            ? <span className="logprob-special">↵</span>
            : visible(token.token, i)}
          {hoveredIndex === i && <TokenTooltip token={token} />}
        </span>
      ))}
      {(shown < tokens.length || overflow > 0) && (
        <span
          className="logprob-token"
          onMouseEnter={() => setHoveredIndex(shown)}
          onMouseLeave={() => setHoveredIndex(null)}
          title={`End of turn: ${JSON.stringify(
            (overflow ? tokens[shown - 1].token.slice(-overflow) : '')
            + tokens.slice(shown).map((t) => t.token).join(''),
          )}`}
        >
          <span className="logprob-special">↵</span>
          {hoveredIndex === shown && shown < tokens.length && <TokenTooltip token={tokens[shown]} />}
        </span>
      )}
    </span>
  )
}
