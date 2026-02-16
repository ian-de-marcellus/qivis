import { useState, useEffect, useRef } from 'react'
import './ThinkingSection.css'

interface ThinkingSectionProps {
  thinkingContent: string
  isStreaming?: boolean
}

export function ThinkingSection({ thinkingContent, isStreaming = false }: ThinkingSectionProps) {
  const [expanded, setExpanded] = useState(isStreaming)
  const contentRef = useRef<HTMLDivElement>(null)

  // Auto-expand when streaming starts
  useEffect(() => {
    if (isStreaming) setExpanded(true)
  }, [isStreaming])

  // Auto-scroll to bottom during streaming
  useEffect(() => {
    if (isStreaming && expanded && contentRef.current) {
      contentRef.current.scrollTop = contentRef.current.scrollHeight
    }
  }, [thinkingContent, isStreaming, expanded])

  const wordCount = thinkingContent.split(/\s+/).filter(Boolean).length

  return (
    <div className="thinking-section">
      <button
        className="thinking-toggle"
        onClick={() => setExpanded(!expanded)}
        aria-label={expanded ? 'Collapse thinking' : 'Expand thinking'}
      >
        <span className={`thinking-toggle-chevron ${expanded ? 'expanded' : ''}`}>
          &#x25B6;
        </span>
        Thinking
        <span className="thinking-toggle-count">
          {wordCount.toLocaleString()} words
        </span>
      </button>

      {expanded && (
        <div
          ref={contentRef}
          className={`thinking-content${isStreaming ? ' streaming' : ''}`}
        >
          {thinkingContent}
          {isStreaming && <span className="thinking-cursor" />}
        </div>
      )}
    </div>
  )
}
