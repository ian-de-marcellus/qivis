import { useState } from 'react'
import type { GenerateRequest, ProviderInfo, SamplingParams } from '../../api/types.ts'
import { SAMPLING_PRESETS, detectPreset, type PresetName } from './samplingPresets.ts'
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
  samplingDefaults: SamplingParams | null
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
  samplingDefaults,
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

  // Sampling state — initialize from tree defaults
  const sp = samplingDefaults ?? {}
  const [temperature, setTemperature] = useState(sp.temperature != null ? String(sp.temperature) : '')
  const [topP, setTopP] = useState(sp.top_p != null ? String(sp.top_p) : '')
  const [topK, setTopK] = useState(sp.top_k != null ? String(sp.top_k) : '')
  const [maxTokens, setMaxTokens] = useState(sp.max_tokens != null ? String(sp.max_tokens) : '')
  const [frequencyPenalty, setFrequencyPenalty] = useState(
    sp.frequency_penalty != null ? String(sp.frequency_penalty) : '',
  )
  const [presencePenalty, setPresencePenalty] = useState(
    sp.presence_penalty != null ? String(sp.presence_penalty) : '',
  )
  const [extendedThinking, setExtendedThinking] = useState(sp.extended_thinking ?? false)
  const [thinkingBudget, setThinkingBudget] = useState(
    String(sp.thinking_budget ?? 10000),
  )

  const [count, setCount] = useState('1')
  const [stream, setStream] = useState(streamDefault)

  const canSubmit =
    mode === 'regenerate'
      ? !isGenerating
      : content.trim().length > 0 && !isGenerating

  const handlePresetChange = (presetName: PresetName) => {
    if (presetName === 'custom') return
    const preset = SAMPLING_PRESETS[presetName]
    if (!preset) return
    setTemperature(preset.temperature != null ? String(preset.temperature) : '')
    setTopP(preset.top_p != null ? String(preset.top_p) : '')
    if (preset.top_k != null) setTopK(String(preset.top_k))
    if (preset.max_tokens != null) setMaxTokens(String(preset.max_tokens))
    if (preset.frequency_penalty != null) setFrequencyPenalty(String(preset.frequency_penalty))
    if (preset.presence_penalty != null) setPresencePenalty(String(preset.presence_penalty))
  }

  const currentPreset = detectPreset(temperature, topP)

  const handleSubmit = () => {
    if (!canSubmit) return

    const parsedCount = parseInt(count, 10)
    const n = parsedCount > 1 ? parsedCount : undefined

    // Build sampling_params from all fields — only include explicitly set values
    const samplingParams: SamplingParams = {}
    if (temperature) samplingParams.temperature = parseFloat(temperature)
    if (topP) samplingParams.top_p = parseFloat(topP)
    if (topK) samplingParams.top_k = parseInt(topK, 10)
    if (maxTokens) samplingParams.max_tokens = parseInt(maxTokens, 10)
    if (frequencyPenalty) samplingParams.frequency_penalty = parseFloat(frequencyPenalty)
    if (presencePenalty) samplingParams.presence_penalty = parseFloat(presencePenalty)
    if (extendedThinking) {
      samplingParams.extended_thinking = true
      samplingParams.thinking_budget = parseInt(thinkingBudget, 10) || 10000
    }

    const overrides: GenerateRequest = {
      provider: provider || undefined,
      model: model || undefined,
      system_prompt: systemPrompt || undefined,
      sampling_params: Object.keys(samplingParams).length > 0 ? samplingParams : undefined,
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

            <div className="fork-settings-divider" />

            <div className="fork-setting-row">
              <label>Preset</label>
              <select
                value={currentPreset}
                onChange={(e) => handlePresetChange(e.target.value as PresetName)}
              >
                {Object.entries(SAMPLING_PRESETS).map(([key, p]) => (
                  <option key={key} value={key}>{p.label}</option>
                ))}
                <option value="custom">Custom</option>
              </select>
            </div>

            <div className="fork-setting-row-pair">
              <div className="fork-setting-row">
                <label>Temperature</label>
                <input
                  type="number"
                  step="0.05"
                  min="0"
                  max="2"
                  value={temperature}
                  onChange={(e) => setTemperature(e.target.value)}
                  placeholder="default"
                />
              </div>
              <div className="fork-setting-row">
                <label>Top P</label>
                <input
                  type="number"
                  step="0.05"
                  min="0"
                  max="1"
                  value={topP}
                  onChange={(e) => setTopP(e.target.value)}
                  placeholder="default"
                />
              </div>
            </div>

            <div className="fork-setting-row-pair">
              <div className="fork-setting-row">
                <label>Top K</label>
                <input
                  type="number"
                  step="1"
                  min="0"
                  value={topK}
                  onChange={(e) => setTopK(e.target.value)}
                  placeholder="default"
                />
              </div>
              <div className="fork-setting-row">
                <label>Max tokens</label>
                <input
                  type="number"
                  step="256"
                  min="1"
                  value={maxTokens}
                  onChange={(e) => setMaxTokens(e.target.value)}
                  placeholder="2048"
                />
              </div>
            </div>

            <div className="fork-setting-row-pair">
              <div className="fork-setting-row">
                <label>Freq penalty</label>
                <input
                  type="number"
                  step="0.1"
                  min="-2"
                  max="2"
                  value={frequencyPenalty}
                  onChange={(e) => setFrequencyPenalty(e.target.value)}
                  placeholder="default"
                />
              </div>
              <div className="fork-setting-row">
                <label>Pres penalty</label>
                <input
                  type="number"
                  step="0.1"
                  min="-2"
                  max="2"
                  value={presencePenalty}
                  onChange={(e) => setPresencePenalty(e.target.value)}
                  placeholder="default"
                />
              </div>
            </div>

            <div className="fork-settings-divider" />

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
            <div className="fork-setting-row fork-setting-toggle">
              <label>
                <input
                  type="checkbox"
                  checked={extendedThinking}
                  onChange={(e) => setExtendedThinking(e.target.checked)}
                />
                Extended thinking
              </label>
            </div>
            {extendedThinking && (
              <div className="fork-setting-row">
                <label>Thinking budget</label>
                <input
                  type="number"
                  min="1024"
                  step="1024"
                  value={thinkingBudget}
                  onChange={(e) => setThinkingBudget(e.target.value)}
                  placeholder="10000"
                />
              </div>
            )}
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
