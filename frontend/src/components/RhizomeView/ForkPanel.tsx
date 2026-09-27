import { useEffect, useRef, useState } from 'react'
import type { GenerateRequest, ProviderInfo, SamplingParams } from '../../api/types.ts'
import { useRhizomeData, useRhizomeStore } from '../../store/rhizomeStore.ts'
import { AdvancedGroup, AdvancedSection } from '../shared/AdvancedSection.tsx'
import { ModelPicker } from '../shared/ModelPicker.tsx'
import { findModel, type ModelChoice } from '../shared/modelChoice.ts'
import { SamplingParamsPanel, type SamplingParamValues } from '../shared/SamplingParamsPanel.tsx'
import { type GenerationModeChoice, effectiveMode } from './generationMode.ts'
import { ModeSelect } from './ModeSelect.tsx'
import './ForkPanel.css'

interface ForkPanelProps {
  mode: 'fork' | 'regenerate' | 'prefill' | 'generate'
  onForkSubmit: (content: string, overrides: GenerateRequest) => void
  onRegenerateSubmit: (overrides: GenerateRequest) => void
  onPrefillSubmit?: (content: string) => void
  onPrefillContinue?: (content: string, overrides: GenerateRequest) => void
  onCancel: () => void
  isGenerating: boolean
  providers: ProviderInfo[]
  defaults: {
    provider: string | null
    model: string | null
    systemPrompt: string | null
    /** Mode of the last assistant turn on the branch, if any */
    mode?: 'chat' | 'completion'
  }
  streamDefault: boolean
  samplingDefaults: SamplingParams | null
}

function toSamplingParams(v: SamplingParamValues): SamplingParams {
  const sp: SamplingParams = {}
  if (v.temperature) sp.temperature = parseFloat(v.temperature)
  if (v.topP) sp.top_p = parseFloat(v.topP)
  if (v.topK) sp.top_k = parseInt(v.topK, 10)
  if (v.maxTokens) sp.max_tokens = parseInt(v.maxTokens, 10)
  if (v.frequencyPenalty) sp.frequency_penalty = parseFloat(v.frequencyPenalty)
  if (v.presencePenalty) sp.presence_penalty = parseFloat(v.presencePenalty)
  sp.extended_thinking = v.useThinking
  if (v.useThinking) sp.thinking_budget = parseInt(v.thinkingBudget, 10) || 10000
  return sp
}

export function ForkPanel({
  mode,
  onForkSubmit,
  onRegenerateSubmit,
  onPrefillSubmit,
  onPrefillContinue,
  onCancel,
  isGenerating,
  providers,
  defaults,
  streamDefault,
  samplingDefaults,
}: ForkPanelProps) {
  const { currentRhizome, models } = useRhizomeData()
  // One source of truth for the system prompt: the main input's override, else the rhizome default
  const systemPromptOverride = useRhizomeStore(s => s.systemPromptOverride)
  const [content, setContent] = useState('')

  // Start from the branch's model (or the rhizome default, or the first available provider)
  const [choice, setChoice] = useState<ModelChoice>(() => ({
    provider: providers.find((p) => p.name === defaults.provider)?.name ?? providers[0]?.name ?? '',
    model: defaults.model ?? '',
  }))
  // Follow the branch, like the model: regenerating after a chat-mode GPT turn
  // in a completion-mode rhizome should stay chat
  const [generationMode, setGenerationMode] = useState<GenerationModeChoice>(defaults.mode ?? '')
  const [systemPrompt, setSystemPrompt] = useState(systemPromptOverride ?? defaults.systemPrompt ?? '')

  const selectedProvider = providers.find((p) => p.name === choice.provider)
  const supportedParams = selectedProvider?.supported_params ?? []
  const entry = findModel(models, choice)
  const completionOnly = selectedProvider ? !selectedProvider.supported_modes.includes('chat') : false
  const rhizomeMode = currentRhizome?.metadata?.generation_mode === 'completion' ? 'completion' : 'chat'
  const modelMode = completionOnly ? 'completion' : entry?.mode ?? rhizomeMode
  const effective = generationMode || modelMode
  // An explicit mode for dual-mode providers: the user's choice, else the model's own
  const modeToSend = effectiveMode(selectedProvider, generationMode || (entry ? entry.mode : ''))

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

  const overrides = (withCount: boolean): GenerateRequest => {
    const samplingParams = toSamplingParams(samplingValues)
    const parsedCount = parseInt(count, 10)
    return {
      provider: choice.provider || undefined,
      model: choice.model || undefined,
      system_prompt: effective === 'chat' ? (systemPrompt || undefined) : undefined,
      sampling_params: Object.keys(samplingParams).length > 0 ? samplingParams : undefined,
      ...(withCount && parsedCount > 1 && { n: parsedCount }),
      stream,
      mode: modeToSend,
    }
  }

  const advanced = (
    <AdvancedSection storageKey="fork" summary="Mode · System prompt · Sampling · Stream">
      <AdvancedGroup title="Format">
        <ModeSelect
          provider={selectedProvider}
          value={generationMode}
          onChange={setGenerationMode}
          modelMode={entry?.mode}
        />
        {effective === 'chat' && (
          <div className="fork-setting-row">
            <label>System prompt</label>
            <textarea
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              rows={2}
              placeholder="System prompt for this generation..."
            />
          </div>
        )}
      </AdvancedGroup>
      <AdvancedGroup title="Sampling">
        <SamplingParamsPanel
          values={samplingValues}
          onChange={handleSamplingChange}
          supportedParams={supportedParams}
          providerName={choice.provider}
        />
      </AdvancedGroup>
      <AdvancedGroup title="Display">
        <div className="fork-setting-row fork-setting-toggle">
          <label>
            <input type="checkbox" checked={stream} onChange={(e) => setStream(e.target.checked)} />
            Stream
          </label>
        </div>
      </AdvancedGroup>
    </AdvancedSection>
  )

  const modelRow = (
    <div className="fork-setting-row">
      <label>Model</label>
      <ModelPicker value={choice} onChange={setChoice} models={models} providers={providers} />
    </div>
  )

  // Prefill mode: Save (manual node) or Continue (generate with prefill)
  if (mode === 'prefill') {
    const handlePrefillContinue = () => {
      if (!content.trim() || !onPrefillContinue) return
      onPrefillContinue(content.trim(), overrides(false))
    }

    const handlePrefillKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        handlePrefillContinue()
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
            placeholder="Write the beginning of the assistant's response..."
            rows={3}
            autoFocus
          />

          {onPrefillContinue && (
            <div className="fork-settings">
              {modelRow}
              {advanced}
            </div>
          )}

          <span className="fork-panel-hint">Cmd+Enter to continue, Esc to cancel</span>
          <span className="fork-panel-kindness">You're writing the model's memory. Be kind.</span>
          <div className="fork-panel-actions">
            <button
              className="fork-submit-btn fork-submit-secondary"
              onClick={() => content.trim() && onPrefillSubmit?.(content.trim())}
              disabled={!content.trim()}
            >
              Save only
            </button>
            {onPrefillContinue && (
              <button
                className="fork-submit-btn"
                onClick={handlePrefillContinue}
                disabled={!content.trim() || isGenerating}
              >
                {isGenerating ? 'Generating...' : 'Continue'}
              </button>
            )}
          </div>
        </div>
      </div>
    )
  }

  const canSubmit =
    mode === 'regenerate' || mode === 'generate'
      ? !isGenerating
      : content.trim().length > 0 && !isGenerating

  const handleSubmit = () => {
    if (!canSubmit) return
    if (mode === 'regenerate' || mode === 'generate') {
      onRegenerateSubmit(overrides(true))
    } else {
      onForkSubmit(content.trim(), overrides(true))
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

        <div className="fork-settings">
          {modelRow}
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
          {advanced}
        </div>

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
