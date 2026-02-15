import { useState } from 'react'
import type { GenerateRequest } from '../../api/types.ts'
import './ForkPanel.css'

interface ForkPanelProps {
  mode: 'fork' | 'regenerate'
  onForkSubmit: (content: string, overrides: GenerateRequest) => void
  onRegenerateSubmit: (overrides: GenerateRequest) => void
  onCancel: () => void
  isGenerating: boolean
  defaults: {
    provider: string | null
    model: string | null
    systemPrompt: string | null
  }
}

export function ForkPanel({
  mode,
  onForkSubmit,
  onRegenerateSubmit,
  onCancel,
  isGenerating,
  defaults,
}: ForkPanelProps) {
  const [content, setContent] = useState('')
  const [showSettings, setShowSettings] = useState(mode === 'regenerate')

  const [provider, setProvider] = useState(defaults.provider ?? 'anthropic')
  const [model, setModel] = useState(defaults.model ?? '')
  const [systemPrompt, setSystemPrompt] = useState(defaults.systemPrompt ?? '')
  const [temperature, setTemperature] = useState('')

  const canSubmit =
    mode === 'regenerate'
      ? !isGenerating
      : content.trim().length > 0 && !isGenerating

  const handleSubmit = () => {
    if (!canSubmit) return

    const overrides: GenerateRequest = {
      provider: provider || undefined,
      model: model || undefined,
      system_prompt: systemPrompt || undefined,
      sampling_params: temperature ? { temperature: parseFloat(temperature) } : undefined,
    }

    if (mode === 'regenerate') {
      onRegenerateSubmit(overrides)
    } else {
      onForkSubmit(content.trim(), overrides)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    } else if (e.key === 'Escape') {
      onCancel()
    }
  }

  const title = mode === 'regenerate' ? 'Regenerate response' : 'Fork conversation'
  const submitLabel = mode === 'regenerate' ? 'Regenerate' : 'Fork & Generate'

  return (
    <div className="fork-panel">
      <div className="fork-panel-header">
        <span className="fork-panel-title">{title}</span>
        <button className="fork-panel-close" onClick={onCancel}>
          Cancel
        </button>
      </div>

      <div className="fork-panel-body">
        {mode === 'fork' && (
          <textarea
            className="fork-panel-input"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type your forked message..."
            rows={2}
            autoFocus
          />
        )}

        <button
          className="fork-settings-toggle"
          onClick={() => setShowSettings(!showSettings)}
        >
          <span className={`toggle-arrow ${showSettings ? 'expanded' : ''}`}>
            &#9654;
          </span>
          Settings
        </button>

        {showSettings && (
          <div className="fork-settings">
            <div className="fork-setting-row">
              <label>Provider</label>
              <input
                type="text"
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
                placeholder="anthropic"
              />
            </div>
            <div className="fork-setting-row">
              <label>Model</label>
              <input
                type="text"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder="default"
              />
            </div>
            <div className="fork-setting-row">
              <label>System prompt</label>
              <textarea
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                rows={2}
                placeholder="Override system prompt..."
              />
            </div>
            <div className="fork-setting-row">
              <label>Temperature</label>
              <input
                type="number"
                step="0.1"
                min="0"
                max="2"
                value={temperature}
                onChange={(e) => setTemperature(e.target.value)}
                placeholder="default"
              />
            </div>
          </div>
        )}

        <button
          className="fork-submit-btn"
          onClick={handleSubmit}
          disabled={!canSubmit}
        >
          {isGenerating ? 'Generating...' : submitLabel}
        </button>
      </div>
    </div>
  )
}
