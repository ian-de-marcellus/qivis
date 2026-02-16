import { useState } from 'react'
import type { GenerateRequest, ProviderInfo } from '../../api/types.ts'
import './ForkPanel.css'

interface ForkPanelProps {
  mode: 'fork' | 'regenerate'
  onForkSubmit: (content: string, overrides: GenerateRequest) => void
  onRegenerateSubmit: (overrides: GenerateRequest) => void
  onCancel: () => void
  isGenerating: boolean
  providers: ProviderInfo[]
  defaults: {
    provider: string | null
    model: string | null
    systemPrompt: string | null
  }
  streamDefault: boolean
}

export function ForkPanel({
  mode,
  onForkSubmit,
  onRegenerateSubmit,
  onCancel,
  isGenerating,
  providers,
  defaults,
  streamDefault,
}: ForkPanelProps) {
  const [content, setContent] = useState('')
  const [showSettings, setShowSettings] = useState(mode === 'regenerate')

  // Default to tree's provider if it's available, otherwise first provider
  const defaultProvider =
    providers.find((p) => p.name === defaults.provider)?.name ??
    providers[0]?.name ??
    ''
  const [provider, setProvider] = useState(defaultProvider)
  const [model, setModel] = useState(defaults.model ?? '')

  const selectedProvider = providers.find((p) => p.name === provider)
  const suggestedModels = selectedProvider?.models ?? []
  const [systemPrompt, setSystemPrompt] = useState(defaults.systemPrompt ?? '')
  const [temperature, setTemperature] = useState('')
  const [count, setCount] = useState('1')
  const [stream, setStream] = useState(streamDefault)

  const canSubmit =
    mode === 'regenerate'
      ? !isGenerating
      : content.trim().length > 0 && !isGenerating

  const handleSubmit = () => {
    if (!canSubmit) return

    const parsedCount = parseInt(count, 10)
    const n = parsedCount > 1 ? parsedCount : undefined

    const overrides: GenerateRequest = {
      provider: provider || undefined,
      model: model || undefined,
      system_prompt: systemPrompt || undefined,
      sampling_params: temperature ? { temperature: parseFloat(temperature) } : undefined,
      n,
      stream,
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
              {providers.length > 0 ? (
                <select
                  value={provider}
                  onChange={(e) => {
                    setProvider(e.target.value)
                    setModel('')
                  }}
                >
                  {providers.map((p) => (
                    <option key={p.name} value={p.name}>
                      {p.name}
                    </option>
                  ))}
                </select>
              ) : (
                <select disabled>
                  <option>No providers available</option>
                </select>
              )}
            </div>
            <div className="fork-setting-row">
              <label>Model</label>
              <input
                type="text"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder={suggestedModels[0] ?? 'default'}
                list="fork-model-suggestions"
              />
              <datalist id="fork-model-suggestions">
                {suggestedModels.map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
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
            <div className="fork-setting-row">
              <label>Count</label>
              <input
                type="number"
                min="1"
                max="10"
                value={count}
                onChange={(e) => setCount(e.target.value)}
                placeholder="1"
              />
            </div>
            <div className="fork-setting-row fork-setting-toggle">
              <label>
                <input
                  type="checkbox"
                  checked={stream}
                  onChange={(e) => setStream(e.target.checked)}
                />
                Stream
              </label>
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
