import { useEffect, useRef, useState } from 'react'
import './ForkPanel.css'

interface WriteResponsePanelProps {
  onSubmit: (content: string) => void
  onCancel: () => void
}

export function WriteResponsePanel({ onSubmit, onCancel }: WriteResponsePanelProps) {
  const [content, setContent] = useState('')
  const panelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    panelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [])

  const handleSubmit = () => {
    const trimmed = content.trim()
    if (!trimmed) return
    onSubmit(trimmed)
  }

  return (
    <div className="fork-panel" ref={panelRef}>
      <div className="fork-panel-header">
        <span className="fork-panel-title">Write assistant response</span>
        <button className="fork-panel-close" onClick={onCancel}>Cancel</button>
      </div>
      <div className="fork-panel-body">
        <textarea
          className="fork-panel-input"
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="Write the assistant's response..."
          rows={4}
          autoFocus
        />
        <button
          className="fork-submit-btn"
          onClick={handleSubmit}
          disabled={!content.trim()}
        >
          Save
        </button>
      </div>
    </div>
  )
}
