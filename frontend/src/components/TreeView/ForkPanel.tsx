import { useEffect, useRef, useState } from 'react'
import type { GenerateRequest, ProviderInfo, SamplingParams } from '../../api/types.ts'
import { SamplingParamsPanel, type SamplingParamValues } from '../shared/SamplingParamsPanel.tsx'
import './ForkPanel.css'

interface ForkPanelProps {
  mode: 'fork' | 'regenerate' | 'prefill' | 'generate'
  onForkSubmit: (content: string, overrides: GenerateRequest) => void
  onRegenerateSubmit: (overrides: GenerateRequest) => void
  onPrefillSubmit?: (content: string) => void
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
  onPrefillSubmit,
  onCancel,
  isGenerating,
  providers,
  defaults,
  streamDefault,
  samplingDefaults,
}: ForkPanelProps) {
  const [content, setContent] = useState('')
  const [showSettings, setShowSettings] = useState(mode === 'regenerate' || mode === 'generate')

  // Default to tree's provider if it's available, otherwise first provider
  const defaultProvider =
    providers.find((p) => p.name === defaults.provider)?.name ??
    providers[0]?.name ??
    ''
  const [provider, setProvider] = useState(defaultProvider)
  const [model, setModel] = useState(defaults.model ?? '')

  const selectedProvider = providers.find((p) => p.name === provider)
  const suggestedModels = selectedProvider?.models ?? []
  const supportedParams = selectedProvider?.supported_params ?? []
  const [systemPrompt, setSystemPrompt] = useState(defaults.systemPrompt ?? '')

  // Sampling state — initialize from tree defaults
  const sp = samplingDefaults ?? {}
  const [samplingValues, setSamplingValues] = useState<SamplingParamValues>({
    temperature: sp.temperature != null ? String(sp.temperature) : '',
    topP: sp.top_p != null ? String(sp.top_p) : '',
    topK: sp.top_k != null ? String(sp.top_k) : '',
    maxTokens: sp.max_tokens != null ? String(sp.max_tokens) : '',
    frequencyPenalty: sp.frequency_penalty != null ? String(sp.frequency_penalty) : '',
    presencePenalty: sp.presence_penalty != null ? String(sp.presence_penalty) : '',
    useThinking: sp.extended_thinking ?? false,
    thinkingBudget: String(sp.thinking_budget ?? 10000),
  })
  const handleSamplingChange = (field: keyof SamplingParamValues, value: string | boolean) => {
    setSamplingValues(prev => ({ ...prev, [field]: value }))
  }

  const [count, setCount] = useState('1')
  const [stream, setStream] = useState(streamDefault)

  const panelRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    panelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [])

  const canSubmit =
    mode === 'regenerate' || mode === 'generate'
      ? !isGenerating
      : content.trim().length > 0 && !isGenerating

  // Prefill mode: simple submit, no generation
  if (mode === 'prefill') {
    const handlePrefillKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        if (content.trim()) onPrefillSubmit?.(content.trim())
      } else if (e.key === 'Escape') {
        onCancel()
      }
    }

    return (
      <div className="fork-panel" ref={panelRef}>
        <div className="fork-panel-header">
          <span className="fork-panel-title">Prefill assistant response</span>
          <button className="fork-panel-close" onClick={onCancel}>
            Cancel
          </button>
        </div>
        <div className="fork-panel-body">
          <textarea
            className="form-input fork-panel-input"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            onKeyDown={handlePrefillKeyDown}
            placeholder="Write the assistant's response..."
            rows={3}
            autoFocus
          />
          <span className="fork-panel-hint">Cmd+Enter to save, Esc to cancel</span>
          <span className="fork-panel-kindness">You're writing the model's memory. Be kind.</span>
          <button
            className="fork-submit-btn"
            onClick={() => content.trim() && onPrefillSubmit?.(content.trim())}
            disabled={!content.trim()}
          >
            Save
          </button>
        </div>
      </div>
    )
  }

  const handleSubmit = () => {
    if (!canSubmit) return

    const parsedCount = parseInt(count, 10)
    const n = parsedCount > 1 ? parsedCount : undefined

    // Build sampling_params from all fields — only include explicitly set values
    const samplingParams: SamplingParams = {}
    if (samplingValues.temperature) samplingParams.temperature = parseFloat(samplingValues.temperature)
    if (samplingValues.topP) samplingParams.top_p = parseFloat(samplingValues.topP)
    if (samplingValues.topK) samplingParams.top_k = parseInt(samplingValues.topK, 10)
    if (samplingValues.maxTokens) samplingParams.max_tokens = parseInt(samplingValues.maxTokens, 10)
    if (samplingValues.frequencyPenalty) samplingParams.frequency_penalty = parseFloat(samplingValues.frequencyPenalty)
    if (samplingValues.presencePenalty) samplingParams.presence_penalty = parseFloat(samplingValues.presencePenalty)
    samplingParams.extended_thinking = samplingValues.useThinking
    if (samplingValues.useThinking) {
      samplingParams.thinking_budget = parseInt(samplingValues.thinkingBudget, 10) || 10000
    }

    const overrides: GenerateRequest = {
      provider: provider || undefined,
      model: model || undefined,
      system_prompt: systemPrompt || undefined,
      sampling_params: Object.keys(samplingParams).length > 0 ? samplingParams : undefined,
      n,
      stream,
    }

    if (mode === 'regenerate' || mode === 'generate') {
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

  const title = mode === 'regenerate' ? 'Regenerate response'
    : mode === 'generate' ? 'Generate response'
    : 'Fork conversation'
  const submitLabel = mode === 'regenerate' ? 'Regenerate'
    : mode === 'generate' ? 'Generate'
    : 'Fork & Generate'

  return (
    <div className="fork-panel" ref={panelRef}>
      <div className="fork-panel-header">
        <span className="fork-panel-title">{title}</span>
        <button className="fork-panel-close" onClick={onCancel}>
          Cancel
        </button>
      </div>

      <div className="fork-panel-body">
        {mode === 'fork' && (
          <textarea
            className="form-input fork-panel-input"
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

            <SamplingParamsPanel
              values={samplingValues}
              onChange={handleSamplingChange}
              supportedParams={supportedParams}
              providerName={provider}
            />

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
