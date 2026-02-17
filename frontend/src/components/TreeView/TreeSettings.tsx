import { useEffect, useState } from 'react'
import type { PatchTreeRequest, SamplingParams } from '../../api/types.ts'
import { useTreeStore } from '../../store/treeStore.ts'
import { SAMPLING_PRESETS, detectPreset, type PresetName } from './samplingPresets.ts'
import './TreeSettings.css'

interface TreeSettingsProps {
  graphOpen?: boolean
  onToggleGraph?: () => void
}

export function TreeSettings({ graphOpen, onToggleGraph }: TreeSettingsProps) {
  // Close graph when opening groups panel (mutual exclusion for right pane)
  const { currentTree, updateTree, providers, fetchProviders, canvasOpen, setCanvasOpen, digressionPanelOpen, setDigressionPanelOpen } = useTreeStore()
  const [isOpen, setIsOpen] = useState(false)
  const [isEditingTitle, setIsEditingTitle] = useState(false)

  // Local form state (synced from tree on open/switch)
  const [title, setTitle] = useState('')
  const [provider, setProvider] = useState('')
  const [model, setModel] = useState('')
  const [systemPrompt, setSystemPrompt] = useState('')

  // Sampling defaults state
  const [temperature, setTemperature] = useState('')
  const [topP, setTopP] = useState('')
  const [topK, setTopK] = useState('')
  const [maxTokens, setMaxTokens] = useState('')
  const [frequencyPenalty, setFrequencyPenalty] = useState('')
  const [presencePenalty, setPresencePenalty] = useState('')
  const [extendedThinking, setExtendedThinking] = useState(false)
  const [thinkingBudget, setThinkingBudget] = useState('10000')

  // Sync form state when tree changes or panel opens
  useEffect(() => {
    if (currentTree) {
      setTitle(currentTree.title ?? '')
      setProvider(currentTree.default_provider ?? '')
      setModel(currentTree.default_model ?? '')
      setSystemPrompt(currentTree.default_system_prompt ?? '')

      // Sampling defaults — read from default_sampling_params, fall back to metadata
      const sp = currentTree.default_sampling_params
      const meta = currentTree.metadata
      setTemperature(sp?.temperature != null ? String(sp.temperature) : '')
      setTopP(sp?.top_p != null ? String(sp.top_p) : '')
      setTopK(sp?.top_k != null ? String(sp.top_k) : '')
      setMaxTokens(sp?.max_tokens != null ? String(sp.max_tokens) : '')
      setFrequencyPenalty(sp?.frequency_penalty != null ? String(sp.frequency_penalty) : '')
      setPresencePenalty(sp?.presence_penalty != null ? String(sp.presence_penalty) : '')

      // Extended thinking: prefer default_sampling_params, fall back to metadata
      const thinkingOn = sp?.extended_thinking ?? !!meta?.extended_thinking
      setExtendedThinking(thinkingOn)
      setThinkingBudget(
        String(sp?.thinking_budget ?? (meta?.thinking_budget as number | undefined) ?? 10000),
      )
    }
  }, [currentTree?.tree_id, isOpen])

  // Fetch providers when panel opens
  useEffect(() => {
    if (isOpen) fetchProviders()
  }, [isOpen, fetchProviders])

  if (!currentTree) return null

  const selectedProvider = providers.find((p) => p.name === provider)
  const suggestedModels = selectedProvider?.models ?? []
  const supportedParams = selectedProvider?.supported_params ?? []
  const isSupported = (param: string) => !provider || supportedParams.length === 0 || supportedParams.includes(param)

  // Build what the current sampling params "should be" from form
  const formSamplingParams: SamplingParams = {}
  if (temperature) formSamplingParams.temperature = parseFloat(temperature)
  if (topP) formSamplingParams.top_p = parseFloat(topP)
  if (topK) formSamplingParams.top_k = parseInt(topK, 10)
  if (maxTokens) formSamplingParams.max_tokens = parseInt(maxTokens, 10)
  if (frequencyPenalty) formSamplingParams.frequency_penalty = parseFloat(frequencyPenalty)
  if (presencePenalty) formSamplingParams.presence_penalty = parseFloat(presencePenalty)
  if (extendedThinking) {
    formSamplingParams.extended_thinking = true
    formSamplingParams.thinking_budget = parseInt(thinkingBudget, 10) || 10000
  }

  // Compare form sampling params to current tree
  const currentSp = currentTree.default_sampling_params ?? {}
  const samplingChanged = JSON.stringify(formSamplingParams) !== JSON.stringify(
    Object.fromEntries(
      Object.entries(currentSp).filter(([, v]) => v != null && v !== false),
    ),
  )

  const hasChanges =
    title !== (currentTree.title ?? '') ||
    provider !== (currentTree.default_provider ?? '') ||
    model !== (currentTree.default_model ?? '') ||
    systemPrompt !== (currentTree.default_system_prompt ?? '') ||
    samplingChanged

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

  const handleSave = async () => {
    if (!hasChanges) return
    const req: PatchTreeRequest = {}
    if (title !== (currentTree.title ?? '')) req.title = title || null
    if (provider !== (currentTree.default_provider ?? ''))
      req.default_provider = provider || null
    if (model !== (currentTree.default_model ?? ''))
      req.default_model = model || null
    if (systemPrompt !== (currentTree.default_system_prompt ?? ''))
      req.default_system_prompt = systemPrompt || null

    if (samplingChanged) {
      req.default_sampling_params = Object.keys(formSamplingParams).length > 0
        ? formSamplingParams
        : null
    }

    // If metadata still has extended_thinking, clear it now that we use default_sampling_params
    if (currentTree.metadata?.extended_thinking != null) {
      const cleanMeta = { ...currentTree.metadata }
      delete cleanMeta.extended_thinking
      delete cleanMeta.thinking_budget
      req.metadata = cleanMeta
    }

    await updateTree(currentTree.tree_id, req)
    setIsOpen(false)
  }

  const handleTitleBlur = async () => {
    setIsEditingTitle(false)
    if (title !== (currentTree.title ?? '') && title.trim()) {
      await updateTree(currentTree.tree_id, { title: title.trim() })
    } else {
      setTitle(currentTree.title ?? '')
    }
  }

  const handleTitleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      ;(e.target as HTMLInputElement).blur()
    } else if (e.key === 'Escape') {
      setTitle(currentTree.title ?? '')
      setIsEditingTitle(false)
    }
  }

  return (
    <div className="tree-settings">
      <div className="tree-settings-bar">
        {isEditingTitle ? (
          <input
            className="tree-title-input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={handleTitleBlur}
            onKeyDown={handleTitleKeyDown}
            autoFocus
          />
        ) : (
          <span
            className="tree-title-display"
            onClick={() => setIsEditingTitle(true)}
            title="Click to rename"
          >
            {currentTree.title || 'Untitled'}
          </span>
        )}
        {onToggleGraph && (
          <button
            className={`graph-toggle ${graphOpen ? 'active' : ''}`}
            onClick={onToggleGraph}
            aria-label={graphOpen ? 'Hide graph view' : 'Show graph view'}
            title={graphOpen ? 'Hide graph' : 'Show graph'}
          >
            <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
              <circle cx="10" cy="4" r="2" />
              <circle cx="5" cy="14" r="2" />
              <circle cx="15" cy="14" r="2" />
              <line x1="10" y1="6" x2="5" y2="12" />
              <line x1="10" y1="6" x2="15" y2="12" />
            </svg>
          </button>
        )}
        <button
          className={`graph-toggle canvas-toggle ${canvasOpen ? 'active' : ''}`}
          onClick={() => setCanvasOpen(!canvasOpen)}
          aria-label={canvasOpen ? 'Hide palimpsest' : 'Show palimpsest'}
          title={canvasOpen ? 'Hide palimpsest' : 'Show palimpsest'}
        >
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <rect x="2" y="3" width="5" height="14" rx="1" />
            <rect x="8" y="3" width="5" height="10" rx="1" />
            <rect x="14" y="3" width="4" height="6" rx="1" />
          </svg>
        </button>
        <button
          className={`graph-toggle ${digressionPanelOpen ? 'active' : ''}`}
          onClick={() => {
            if (!digressionPanelOpen && graphOpen && onToggleGraph) {
              onToggleGraph() // close graph first
            }
            setDigressionPanelOpen(!digressionPanelOpen)
          }}
          aria-label={digressionPanelOpen ? 'Hide digression groups' : 'Show digression groups'}
          title={digressionPanelOpen ? 'Hide groups' : 'Digression groups'}
        >
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <rect x="3" y="3" width="14" height="4" rx="1" />
            <rect x="3" y="9" width="14" height="4" rx="1" />
            <line x1="6" y1="5" x2="6" y2="9" />
            <line x1="14" y1="5" x2="14" y2="9" />
          </svg>
        </button>
        <button
          className={`tree-settings-gear ${isOpen ? 'active' : ''}`}
          onClick={() => setIsOpen(!isOpen)}
          aria-label={isOpen ? 'Close settings' : 'Open settings'}
        >
          <svg viewBox="0 0 20 20" fill="currentColor">
            <path
              fillRule="evenodd"
              d="M8.34 1.804A1 1 0 019.32 1h1.36a1 1 0 01.98.804l.295 1.473c.497.179.971.405 1.416.67l1.4-.587a1 1 0 011.12.272l.962.962a1 1 0 01.272 1.12l-.587 1.4c.265.445.491.919.67 1.416l1.473.295a1 1 0 01.804.98v1.361a1 1 0 01-.804.98l-1.473.295a6.95 6.95 0 01-.67 1.416l.587 1.4a1 1 0 01-.272 1.12l-.962.962a1 1 0 01-1.12.272l-1.4-.587a6.95 6.95 0 01-1.416.67l-.295 1.473a1 1 0 01-.98.804H9.32a1 1 0 01-.98-.804l-.295-1.473a6.95 6.95 0 01-1.416-.67l-1.4.587a1 1 0 01-1.12-.272l-.962-.962a1 1 0 01-.272-1.12l.587-1.4a6.95 6.95 0 01-.67-1.416l-1.473-.295A1 1 0 011 11.68V10.32a1 1 0 01.804-.98l1.473-.295c.179-.497.405-.971.67-1.416l-.587-1.4a1 1 0 01.272-1.12l.962-.962a1 1 0 011.12-.272l1.4.587a6.95 6.95 0 011.416-.67L8.34 1.804zM10 13a3 3 0 100-6 3 3 0 000 6z"
              clipRule="evenodd"
            />
          </svg>
        </button>
      </div>

      {isOpen && (
        <div className="tree-settings-panel">
          <div className="tree-settings-fields">
            <div className="tree-settings-field">
              <label>Default provider</label>
              {providers.length > 0 ? (
                <select
                  value={provider}
                  onChange={(e) => {
                    setProvider(e.target.value)
                    setModel('')
                  }}
                >
                  <option value="">None</option>
                  {providers.map((p) => (
                    <option key={p.name} value={p.name}>
                      {p.name}
                    </option>
                  ))}
                </select>
              ) : (
                <select disabled>
                  <option>Loading...</option>
                </select>
              )}
            </div>

            <div className="tree-settings-field">
              <label>Default model</label>
              <input
                type="text"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder={suggestedModels[0] ?? 'default'}
                list="tree-settings-model-suggestions"
              />
              <datalist id="tree-settings-model-suggestions">
                {suggestedModels.map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            </div>

            <div className="tree-settings-field">
              <label>Default system prompt</label>
              <textarea
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                placeholder="Enter default system prompt..."
                rows={3}
              />
            </div>

            <div className="tree-settings-divider" />

            <div className="tree-settings-section-label">Sampling defaults</div>

            <div className="tree-settings-field">
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

            <div className="tree-settings-row-pair">
              <div className={`tree-settings-field${isSupported('temperature') ? '' : ' unsupported-param'}`}>
                <label>Temperature</label>
                <input
                  type="number"
                  step="0.05"
                  min="0"
                  max="2"
                  value={temperature}
                  onChange={(e) => setTemperature(e.target.value)}
                  placeholder="default"
                  disabled={!isSupported('temperature')}
                  title={isSupported('temperature') ? undefined : `Not supported by ${provider}`}
                />
              </div>
              <div className={`tree-settings-field${isSupported('top_p') ? '' : ' unsupported-param'}`}>
                <label>Top P</label>
                <input
                  type="number"
                  step="0.05"
                  min="0"
                  max="1"
                  value={topP}
                  onChange={(e) => setTopP(e.target.value)}
                  placeholder="default"
                  disabled={!isSupported('top_p')}
                  title={isSupported('top_p') ? undefined : `Not supported by ${provider}`}
                />
              </div>
            </div>

            <div className="tree-settings-row-pair">
              <div className={`tree-settings-field${isSupported('top_k') ? '' : ' unsupported-param'}`}>
                <label>Top K</label>
                <input
                  type="number"
                  step="1"
                  min="0"
                  value={topK}
                  onChange={(e) => setTopK(e.target.value)}
                  placeholder="default"
                  disabled={!isSupported('top_k')}
                  title={isSupported('top_k') ? undefined : `Not supported by ${provider}`}
                />
              </div>
              <div className={`tree-settings-field${isSupported('max_tokens') ? '' : ' unsupported-param'}`}>
                <label>Max tokens</label>
                <input
                  type="number"
                  step="256"
                  min="1"
                  value={maxTokens}
                  onChange={(e) => setMaxTokens(e.target.value)}
                  placeholder="2048"
                  disabled={!isSupported('max_tokens')}
                  title={isSupported('max_tokens') ? undefined : `Not supported by ${provider}`}
                />
              </div>
            </div>

            <div className="tree-settings-row-pair">
              <div className={`tree-settings-field${isSupported('frequency_penalty') ? '' : ' unsupported-param'}`}>
                <label>Freq penalty</label>
                <input
                  type="number"
                  step="0.1"
                  min="-2"
                  max="2"
                  value={frequencyPenalty}
                  onChange={(e) => setFrequencyPenalty(e.target.value)}
                  placeholder="default"
                  disabled={!isSupported('frequency_penalty')}
                  title={isSupported('frequency_penalty') ? undefined : `Not supported by ${provider}`}
                />
              </div>
              <div className={`tree-settings-field${isSupported('presence_penalty') ? '' : ' unsupported-param'}`}>
                <label>Pres penalty</label>
                <input
                  type="number"
                  step="0.1"
                  min="-2"
                  max="2"
                  value={presencePenalty}
                  onChange={(e) => setPresencePenalty(e.target.value)}
                  placeholder="default"
                  disabled={!isSupported('presence_penalty')}
                  title={isSupported('presence_penalty') ? undefined : `Not supported by ${provider}`}
                />
              </div>
            </div>

            <div className={`tree-settings-toggle${isSupported('extended_thinking') ? '' : ' unsupported-param'}`}>
              <label>
                <input
                  type="checkbox"
                  checked={extendedThinking}
                  onChange={(e) => setExtendedThinking(e.target.checked)}
                  disabled={!isSupported('extended_thinking')}
                />
                Extended thinking
              </label>
              {!isSupported('extended_thinking') && (
                <span className="unsupported-hint" title={`Not supported by ${provider}`}>unsupported</span>
              )}
            </div>

            {extendedThinking && isSupported('extended_thinking') && (
              <div className="tree-settings-field">
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

            <div className="tree-settings-divider" />

            <div className="tree-settings-toggle">
              <label>
                <input
                  type="checkbox"
                  checked={!!currentTree.metadata?.include_timestamps}
                  onChange={async (e) => {
                    await updateTree(currentTree.tree_id, {
                      metadata: {
                        ...currentTree.metadata,
                        include_timestamps: e.target.checked,
                      },
                    })
                  }}
                />
                Include timestamps in context
              </label>
            </div>

            <div className="tree-settings-toggle">
              <label>
                <input
                  type="checkbox"
                  checked={currentTree.metadata?.stream_responses !== false}
                  onChange={async (e) => {
                    await updateTree(currentTree.tree_id, {
                      metadata: {
                        ...currentTree.metadata,
                        stream_responses: e.target.checked,
                      },
                    })
                  }}
                />
                Stream responses
              </label>
            </div>

            <div className="tree-settings-toggle">
              <label>
                <input
                  type="checkbox"
                  checked={!!currentTree.metadata?.include_thinking_in_context}
                  onChange={async (e) => {
                    await updateTree(currentTree.tree_id, {
                      metadata: {
                        ...currentTree.metadata,
                        include_thinking_in_context: e.target.checked,
                      },
                    })
                  }}
                />
                Include thinking in context
              </label>
              <span className="tree-settings-note">
                Feed reasoning traces back into subsequent context. Uses significant tokens.
              </span>
            </div>

            <div className="tree-settings-actions">
              <button
                className="tree-settings-save"
                onClick={handleSave}
                disabled={!hasChanges}
              >
                Save defaults
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
