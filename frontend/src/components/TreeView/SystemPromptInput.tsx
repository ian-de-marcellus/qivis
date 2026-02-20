import { useEffect, useState } from 'react'
import { useTreeStore, useTreeData } from '../../store/treeStore.ts'
import './SystemPromptInput.css'

export function SystemPromptInput() {
  const { currentTree } = useTreeData()
  const systemPromptOverride = useTreeStore(s => s.systemPromptOverride)
  const setSystemPromptOverride = useTreeStore(s => s.setSystemPromptOverride)
  const [isExpanded, setIsExpanded] = useState(false)

  const defaultPrompt = currentTree?.default_system_prompt ?? ''
  const displayValue = systemPromptOverride ?? defaultPrompt

  // Reset override when switching trees
  useEffect(() => {
    setSystemPromptOverride(null)
  }, [currentTree?.tree_id, setSystemPromptOverride])

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
