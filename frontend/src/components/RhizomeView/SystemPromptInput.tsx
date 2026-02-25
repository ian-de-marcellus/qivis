import { useEffect, useState } from 'react'
import { useRhizomeStore, useRhizomeData } from '../../store/rhizomeStore.ts'
import './SystemPromptInput.css'

export function SystemPromptInput() {
  const { currentRhizome } = useRhizomeData()
  const systemPromptOverride = useRhizomeStore(s => s.systemPromptOverride)
  const setSystemPromptOverride = useRhizomeStore(s => s.setSystemPromptOverride)
  const [isExpanded, setIsExpanded] = useState(false)

  const defaultPrompt = currentRhizome?.default_system_prompt ?? ''
  const displayValue = systemPromptOverride ?? defaultPrompt

  // Reset override when switching rhizomes
  useEffect(() => {
    setSystemPromptOverride(null)
  }, [currentRhizome?.rhizome_id, setSystemPromptOverride])

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = e.target.value
    // If they type the same as default, clear the override
    if (value === defaultPrompt) {
      setSystemPromptOverride(null)
    } else {
      setSystemPromptOverride(value)
    }
  }

  return (
    <div className="system-prompt">
      <button
        className="system-prompt-toggle"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <span className={`toggle-arrow ${isExpanded ? 'expanded' : ''}`}>&#9654;</span>
        <span>System prompt</span>
        {systemPromptOverride != null && <span className="override-badge">modified</span>}
      </button>

      {isExpanded && (
        <div className="system-prompt-editor">
          <textarea
            className="form-input"
            value={displayValue}
            onChange={handleChange}
            placeholder="Enter system prompt..."
            rows={3}
          />
        </div>
      )}
    </div>
  )
}
