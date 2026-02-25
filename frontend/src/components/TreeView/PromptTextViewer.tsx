/**
 * Expandable monospace display of the rendered prompt text sent to a completion endpoint.
 * Collapsed by default — shows token count and expand chevron.
 * Expanded — scrollable <pre> block with copy-to-clipboard.
 */

import { useState } from 'react'
import './PromptTextViewer.css'

interface PromptTextViewerProps {
  promptText: string
  inputTokens?: number
}

export function PromptTextViewer({ promptText, inputTokens }: PromptTextViewerProps) {
  const [expanded, setExpanded] = useState(false)
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    await navigator.clipboard.writeText(promptText)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const tokenLabel = inputTokens != null
    ? `${inputTokens.toLocaleString()} tok`
    : null

  return (
    <div className="prompt-text-viewer">
      <button
        className="prompt-text-toggle"
        onClick={() => setExpanded(!expanded)}
      >
        <span className={`prompt-text-chevron ${expanded ? 'expanded' : ''}`}>
          &#8250;
        </span>
        <span className="prompt-text-label">Prompt</span>
        {tokenLabel && (
          <span className="prompt-text-tokens">{tokenLabel}</span>
        )}
      </button>
      {expanded && (
        <div className="prompt-text-content">
          <button
            className="prompt-text-copy"
            onClick={handleCopy}
          >
            {copied ? 'Copied' : 'Copy'}
          </button>
          <pre className="prompt-text-pre">{promptText}</pre>
        </div>
      )}
    </div>
  )
}
