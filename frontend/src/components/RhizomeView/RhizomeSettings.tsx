import { useCallback, useEffect, useState } from 'react'
import type { EvictionStrategy, PatchRhizomeRequest, SamplingParams } from '../../api/types.ts'
import { exportRhizome } from '../../api/client.ts'
import { useRhizomeStore, useRhizomeData, useRightPane } from '../../store/rhizomeStore.ts'
import { SamplingParamsPanel, type SamplingParamValues } from '../shared/SamplingParamsPanel.tsx'
import { IconToggleButton } from '../shared/IconToggleButton.tsx'
import { MergePanel } from './MergePanel.tsx'
import './RhizomeSettings.css'

export function RhizomeSettings() {
  const { currentRhizome, providers } = useRhizomeData()
  const { rightPaneMode, canvasOpen } = useRightPane()
  const updateRhizome = useRhizomeStore(s => s.updateRhizome)
  const fetchProviders = useRhizomeStore(s => s.fetchProviders)
  const setCanvasOpen = useRhizomeStore(s => s.setCanvasOpen)
  const setRightPaneMode = useRhizomeStore(s => s.setRightPaneMode)
  const archiveRhizome = useRhizomeStore(s => s.archiveRhizome)
  const unarchiveRhizome = useRhizomeStore(s => s.unarchiveRhizome)
  const fetchRhizomes = useRhizomeStore(s => s.fetchRhizomes)

  const [isOpen, setIsOpen] = useState(false)
  const [mergeOpen, setMergeOpen] = useState(false)
  const [isEditingTitle, setIsEditingTitle] = useState(false)

  // Local form state (synced from rhizome on open/switch)
  const [title, setTitle] = useState('')
  const [provider, setProvider] = useState('')
  const [model, setModel] = useState('')
  const [systemPrompt, setSystemPrompt] = useState('')

  // Sampling defaults state — single object for SamplingParamsPanel
  const [samplingValues, setSamplingValues] = useState<SamplingParamValues>({
    temperature: '',
    topP: '',
    topK: '',
    maxTokens: '',
    frequencyPenalty: '',
    presencePenalty: '',
    useThinking: false,
    thinkingBudget: '10000',
  })
  const handleSamplingChange = (field: keyof SamplingParamValues, value: string | boolean) => {
    setSamplingValues(prev => ({ ...prev, [field]: value }))
  }

  // Metadata toggle state (previously auto-saved, now buffered)
  const [includeTimestamps, setIncludeTimestamps] = useState(false)
  const [streamResponses, setStreamResponses] = useState(true)
  const [includeThinking, setIncludeThinking] = useState(false)
  const [generationMode, setGenerationMode] = useState('chat')
  const [promptTemplate, setPromptTemplate] = useState('raw')
  const [debugContextLimit, setDebugContextLimit] = useState('')

  // Eviction strategy state
  const [evictionMode, setEvictionMode] = useState<'smart' | 'truncate' | 'none'>('smart')
  const [keepFirstTurns, setKeepFirstTurns] = useState('2')
  const [recentTurnsToKeep, setRecentTurnsToKeep] = useState('4')
  const [keepAnchored, setKeepAnchored] = useState(true)
  const [summarizeEvicted, setSummarizeEvicted] = useState(true)
  const [warnThreshold, setWarnThreshold] = useState('0.85')

  // Sync form state when rhizome changes or panel opens
  useEffect(() => {
    if (currentRhizome) {
      setTitle(currentRhizome.title ?? '')
      setProvider(currentRhizome.default_provider ?? '')
      setModel(currentRhizome.default_model ?? '')
      setSystemPrompt(currentRhizome.default_system_prompt ?? '')

      // Sampling defaults — read from default_sampling_params, fall back to metadata
      const sp = currentRhizome.default_sampling_params
      const meta = currentRhizome.metadata
      const thinkingOn = sp?.extended_thinking ?? !!meta?.extended_thinking
      setSamplingValues({
        temperature: sp?.temperature != null ? String(sp.temperature) : '',
        topP: sp?.top_p != null ? String(sp.top_p) : '',
        topK: sp?.top_k != null ? String(sp.top_k) : '',
        maxTokens: sp?.max_tokens != null ? String(sp.max_tokens) : '',
        frequencyPenalty: sp?.frequency_penalty != null ? String(sp.frequency_penalty) : '',
        presencePenalty: sp?.presence_penalty != null ? String(sp.presence_penalty) : '',
        useThinking: thinkingOn,
        thinkingBudget: String(sp?.thinking_budget ?? (meta?.thinking_budget as number | undefined) ?? 10000),
      })

      // Metadata toggles
      setIncludeTimestamps(!!meta?.include_timestamps)
      setStreamResponses(meta?.stream_responses !== false)
      setIncludeThinking(!!meta?.include_thinking_in_context)
      setGenerationMode((meta?.generation_mode as string) ?? 'chat')
      setPromptTemplate((meta?.prompt_template as string) ?? 'raw')
      setDebugContextLimit(meta?.debug_context_limit != null ? String(meta.debug_context_limit) : '')

      // Eviction strategy from metadata
      const es = meta?.eviction_strategy as Partial<EvictionStrategy> | undefined
      setEvictionMode(es?.mode ?? 'smart')
      setKeepFirstTurns(String(es?.keep_first_turns ?? 2))
      setRecentTurnsToKeep(String(es?.recent_turns_to_keep ?? 4))
      setKeepAnchored(es?.keep_anchored ?? true)
      setSummarizeEvicted(es?.summarize_evicted ?? true)
      setWarnThreshold(String(es?.warn_threshold ?? 0.85))
    }
  }, [currentRhizome?.rhizome_id, isOpen])

  // Fetch providers when panel opens
  useEffect(() => {
    if (isOpen) fetchProviders()
  }, [isOpen, fetchProviders])

  if (!currentRhizome) return null

  const selectedProvider = providers.find((p) => p.name === provider)
  const suggestedModels = selectedProvider?.models ?? []
  const supportedParams = selectedProvider?.supported_params ?? []

  // Build what the current sampling params "should be" from form
  const formSamplingParams: SamplingParams = {}
  if (samplingValues.temperature) formSamplingParams.temperature = parseFloat(samplingValues.temperature)
  if (samplingValues.topP) formSamplingParams.top_p = parseFloat(samplingValues.topP)
  if (samplingValues.topK) formSamplingParams.top_k = parseInt(samplingValues.topK, 10)
  if (samplingValues.maxTokens) formSamplingParams.max_tokens = parseInt(samplingValues.maxTokens, 10)
  if (samplingValues.frequencyPenalty) formSamplingParams.frequency_penalty = parseFloat(samplingValues.frequencyPenalty)
  if (samplingValues.presencePenalty) formSamplingParams.presence_penalty = parseFloat(samplingValues.presencePenalty)
  if (samplingValues.useThinking) {
    formSamplingParams.extended_thinking = true
    formSamplingParams.thinking_budget = parseInt(samplingValues.thinkingBudget, 10) || 10000
  }

  // Compare form sampling params to current rhizome
  const currentSp = currentRhizome.default_sampling_params ?? {}
  const samplingChanged = JSON.stringify(formSamplingParams) !== JSON.stringify(
    Object.fromEntries(
      Object.entries(currentSp).filter(([, v]) => v != null && v !== false),
    ),
  )

  const currentMeta = currentRhizome.metadata ?? {}
  const currentEs = currentMeta.eviction_strategy as Partial<EvictionStrategy> | undefined
  const metadataChanged =
    includeTimestamps !== !!currentMeta.include_timestamps ||
    streamResponses !== (currentMeta.stream_responses !== false) ||
    includeThinking !== !!currentMeta.include_thinking_in_context ||
    generationMode !== ((currentMeta.generation_mode as string) ?? 'chat') ||
    promptTemplate !== ((currentMeta.prompt_template as string) ?? 'raw') ||
    debugContextLimit !== (currentMeta.debug_context_limit != null ? String(currentMeta.debug_context_limit) : '') ||
    evictionMode !== (currentEs?.mode ?? 'smart') ||
    (evictionMode === 'smart' && (
      keepFirstTurns !== String(currentEs?.keep_first_turns ?? 2) ||
      recentTurnsToKeep !== String(currentEs?.recent_turns_to_keep ?? 4) ||
      keepAnchored !== (currentEs?.keep_anchored ?? true) ||
      summarizeEvicted !== (currentEs?.summarize_evicted ?? true) ||
      warnThreshold !== String(currentEs?.warn_threshold ?? 0.85)
    ))

  const hasChanges =
    title !== (currentRhizome.title ?? '') ||
    provider !== (currentRhizome.default_provider ?? '') ||
    model !== (currentRhizome.default_model ?? '') ||
    systemPrompt !== (currentRhizome.default_system_prompt ?? '') ||
    samplingChanged ||
    metadataChanged

  const handleSave = async () => {
    if (!hasChanges) return
    const req: PatchRhizomeRequest = {}
    if (title !== (currentRhizome.title ?? '')) req.title = title || null
    if (provider !== (currentRhizome.default_provider ?? ''))
      req.default_provider = provider || null
    if (model !== (currentRhizome.default_model ?? ''))
      req.default_model = model || null
    if (systemPrompt !== (currentRhizome.default_system_prompt ?? ''))
      req.default_system_prompt = systemPrompt || null

    if (samplingChanged) {
      req.default_sampling_params = Object.keys(formSamplingParams).length > 0
        ? formSamplingParams
        : null
    }

    // Build merged metadata from all buffered fields
    if (metadataChanged || currentRhizome.metadata?.extended_thinking != null) {
      const newMeta = { ...currentRhizome.metadata } as Record<string, unknown>
      // Clear legacy thinking fields (now in default_sampling_params)
      delete newMeta.extended_thinking
      delete newMeta.thinking_budget

      // Metadata toggles
      newMeta.include_timestamps = includeTimestamps
      newMeta.stream_responses = streamResponses
      newMeta.include_thinking_in_context = includeThinking
      newMeta.generation_mode = generationMode
      newMeta.prompt_template = promptTemplate
      newMeta.debug_context_limit = debugContextLimit
        ? (parseInt(debugContextLimit, 10) || null)
        : null

      // Eviction strategy
      if (evictionMode === 'smart') {
        newMeta.eviction_strategy = {
          mode: evictionMode,
          keep_first_turns: parseInt(keepFirstTurns, 10) || 2,
          recent_turns_to_keep: parseInt(recentTurnsToKeep, 10) || 4,
          keep_anchored: keepAnchored,
          summarize_evicted: summarizeEvicted,
          warn_threshold: parseFloat(warnThreshold) || 0.85,
        }
      } else {
        newMeta.eviction_strategy = { mode: evictionMode }
      }

      req.metadata = newMeta
    }

    await updateRhizome(currentRhizome.rhizome_id, req)
    setIsOpen(false)
  }

  const handleTitleBlur = async () => {
    setIsEditingTitle(false)
    if (title !== (currentRhizome.title ?? '') && title.trim()) {
      await updateRhizome(currentRhizome.rhizome_id, { title: title.trim() })
    } else {
      setTitle(currentRhizome.title ?? '')
    }
  }

  const handleTitleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      ;(e.target as HTMLInputElement).blur()
    } else if (e.key === 'Escape') {
      setTitle(currentRhizome.title ?? '')
      setIsEditingTitle(false)
    }
  }

  const graphOpen = rightPaneMode === 'graph'
  const isArchived = currentRhizome.archived === 1

  const handleToggleArchive = useCallback(async () => {
    if (isArchived) {
      await unarchiveRhizome(currentRhizome.rhizome_id)
    } else {
      await archiveRhizome(currentRhizome.rhizome_id)
    }
    await fetchRhizomes(true)
  }, [isArchived, currentRhizome.rhizome_id, archiveRhizome, unarchiveRhizome, fetchRhizomes])

  return (
    <div className="rhizome-settings">
      <div className="rhizome-settings-bar">
        {isEditingTitle ? (
          <input
            className="rhizome-title-input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={handleTitleBlur}
            onKeyDown={handleTitleKeyDown}
            autoFocus
          />
        ) : (
          <span
            className="rhizome-title-display"
            onClick={() => setIsEditingTitle(true)}
            title="Click to rename"
          >
            {currentRhizome.title || 'Untitled'}
          </span>
        )}
        <IconToggleButton
          active={graphOpen}
          onClick={() => setRightPaneMode(graphOpen ? null : 'graph')}
          activeLabel="Hide graph view"
          inactiveLabel="Show graph view"
          title={graphOpen ? 'Hide graph' : 'Show graph'}
        >
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <circle cx="10" cy="4" r="2" />
            <circle cx="5" cy="14" r="2" />
            <circle cx="15" cy="14" r="2" />
            <line x1="10" y1="6" x2="5" y2="12" />
            <line x1="10" y1="6" x2="15" y2="12" />
          </svg>
        </IconToggleButton>
        <IconToggleButton
          active={canvasOpen}
          onClick={() => setCanvasOpen(!canvasOpen)}
          activeLabel="Hide palimpsest"
          inactiveLabel="Show palimpsest"
          title={canvasOpen ? 'Hide palimpsest' : 'Show palimpsest'}
        >
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <rect x="2" y="3" width="5" height="14" rx="1" />
            <rect x="8" y="3" width="5" height="10" rx="1" />
            <rect x="14" y="3" width="4" height="6" rx="1" />
          </svg>
        </IconToggleButton>
        <IconToggleButton
          active={rightPaneMode === 'digressions'}
          onClick={() => setRightPaneMode(rightPaneMode === 'digressions' ? null : 'digressions')}
          activeLabel="Hide digression groups"
          inactiveLabel="Show digression groups"
          title={rightPaneMode === 'digressions' ? 'Hide groups' : 'Digression groups'}
        >
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <rect x="3" y="3" width="14" height="4" rx="1" />
            <rect x="3" y="9" width="14" height="4" rx="1" />
            <line x1="6" y1="5" x2="6" y2="9" />
            <line x1="14" y1="5" x2="14" y2="9" />
          </svg>
        </IconToggleButton>
        <IconToggleButton
          active={rightPaneMode === 'research'}
          onClick={() => setRightPaneMode(rightPaneMode === 'research' ? null : 'research')}
          activeLabel="Hide research panel"
          inactiveLabel="Show research panel"
          title={rightPaneMode === 'research' ? 'Hide research' : 'Research panel'}
        >
          <svg viewBox="0 0 20 20" fill="currentColor" stroke="none">
            <path d="M15.3 2.2c-.8 0-1.8.6-3 1.7C10 5.8 7.5 9 6 12l-2 6 1 .7c1.5-1.8 3.8-4.5 5.8-7 1.6-2.3 3.2-5.1 3.8-7.2.2-.8.2-1.6 0-2.1-.1-.3-.3-.5-.5-.5zM3.5 18.5L3 19l1.2-.6-.7.1z"/>
          </svg>
        </IconToggleButton>
        <IconToggleButton
          active={mergeOpen}
          onClick={() => setMergeOpen(!mergeOpen)}
          activeLabel="Close merge panel"
          inactiveLabel="Merge conversation"
          title={mergeOpen ? 'Close merge' : 'Merge conversation'}
        >
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <line x1="10" y1="18" x2="10" y2="8" />
            <line x1="5" y1="2" x2="5" y2="8" />
            <line x1="15" y1="2" x2="15" y2="8" />
            <path d="M5 8 Q5 12 10 12" />
            <path d="M15 8 Q15 12 10 12" />
          </svg>
        </IconToggleButton>
        <button
          className={`rhizome-archive-btn${isArchived ? ' archived' : ''}`}
          onClick={handleToggleArchive}
          title={isArchived ? 'Unarchive this rhizome' : 'Archive this rhizome'}
        >
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <rect x="2" y="3" width="16" height="4" rx="1" />
            <path d="M3 7v8a2 2 0 002 2h10a2 2 0 002-2V7" />
            <line x1="8" y1="11" x2="12" y2="11" />
          </svg>
        </button>
        <IconToggleButton
          active={isOpen}
          onClick={() => setIsOpen(!isOpen)}
          activeLabel="Close settings"
          inactiveLabel="Open settings"
        >
          <svg viewBox="0 0 20 20" fill="currentColor">
            <path
              fillRule="evenodd"
              d="M8.34 1.804A1 1 0 019.32 1h1.36a1 1 0 01.98.804l.295 1.473c.497.179.971.405 1.416.67l1.4-.587a1 1 0 011.12.272l.962.962a1 1 0 01.272 1.12l-.587 1.4c.265.445.491.919.67 1.416l1.473.295a1 1 0 01.804.98v1.361a1 1 0 01-.804.98l-1.473.295a6.95 6.95 0 01-.67 1.416l.587 1.4a1 1 0 01-.272 1.12l-.962.962a1 1 0 01-1.12.272l-1.4-.587a6.95 6.95 0 01-1.416.67l-.295 1.473a1 1 0 01-.98.804H9.32a1 1 0 01-.98-.804l-.295-1.473a6.95 6.95 0 01-1.416-.67l-1.4.587a1 1 0 01-1.12-.272l-.962-.962a1 1 0 01-.272-1.12l.587-1.4a6.95 6.95 0 01-.67-1.416l-1.473-.295A1 1 0 011 11.68V10.32a1 1 0 01.804-.98l1.473-.295c.179-.497.405-.971.67-1.416l-.587-1.4a1 1 0 01.272-1.12l.962-.962a1 1 0 011.12-.272l1.4.587a6.95 6.95 0 011.416-.67L8.34 1.804zM10 13a3 3 0 100-6 3 3 0 000 6z"
              clipRule="evenodd"
            />
          </svg>
        </IconToggleButton>
      </div>

      {mergeOpen && (
        <MergePanel
          rhizomeId={currentRhizome.rhizome_id}
          onClose={() => setMergeOpen(false)}
        />
      )}

      {isOpen && (
        <div className="rhizome-settings-panel">
          <div className="rhizome-settings-fields">
            <div className="rhizome-settings-field">
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

            <div className="rhizome-settings-field">
              <label>Default model</label>
              <input
                type="text"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder={suggestedModels[0] ?? 'default'}
                list="rhizome-settings-model-suggestions"
              />
              <datalist id="rhizome-settings-model-suggestions">
                {suggestedModels.map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            </div>

            <div className="rhizome-settings-field">
              <label>Generation mode</label>
              <div className="mode-selector">
                <button
                  type="button"
                  className={`mode-selector-btn ${generationMode === 'chat' ? 'active' : ''}`}
                  onClick={() => setGenerationMode('chat')}
                >
                  Chat
                </button>
                <button
                  type="button"
                  className={`mode-selector-btn ${generationMode === 'completion' ? 'active' : ''}`}
                  onClick={() => setGenerationMode('completion')}
                >
                  Completion
                </button>
              </div>
              <span className="rhizome-settings-note">
                Chat sends structured messages. Completion renders a text prompt from a template.
              </span>
            </div>

            {generationMode === 'chat' && (
              <div className="rhizome-settings-field">
                <label>Default system prompt</label>
                <textarea
                  value={systemPrompt}
                  onChange={(e) => setSystemPrompt(e.target.value)}
                  placeholder="Enter default system prompt..."
                  rows={3}
                />
              </div>
            )}

            {generationMode === 'completion' && (
              <div className="rhizome-settings-field">
                <label>Prompt template</label>
                <select
                  value={promptTemplate}
                  onChange={(e) => setPromptTemplate(e.target.value)}
                >
                  <option value="raw">Raw (no template)</option>
                  <option value="alpaca">Alpaca</option>
                  <option value="chatml">ChatML</option>
                  <option value="llama3">Llama 3</option>
                </select>
                <span className="rhizome-settings-note">
                  Raw sends plain text — best for base models on remote APIs.
                  Llama 3 uses special tokens that only work with local servers.
                </span>
              </div>
            )}

            <div className="rhizome-settings-divider" />

            <div className="rhizome-settings-section-label">Sampling defaults</div>

            <SamplingParamsPanel
              values={samplingValues}
              onChange={handleSamplingChange}
              supportedParams={supportedParams}
              providerName={provider}
            />

            <div className="rhizome-settings-divider" />

            {generationMode === 'chat' && (
              <div className="rhizome-settings-toggle">
                <label>
                  <input
                    type="checkbox"
                    checked={includeTimestamps}
                    onChange={(e) => setIncludeTimestamps(e.target.checked)}
                  />
                  Include timestamps in context
                </label>
              </div>
            )}

            <div className="rhizome-settings-toggle">
              <label>
                <input
                  type="checkbox"
                  checked={streamResponses}
                  onChange={(e) => setStreamResponses(e.target.checked)}
                />
                Stream responses
              </label>
            </div>

            {generationMode === 'chat' && (
              <div className="rhizome-settings-toggle">
                <label>
                  <input
                    type="checkbox"
                    checked={includeThinking}
                    onChange={(e) => setIncludeThinking(e.target.checked)}
                  />
                  Include thinking in context
                </label>
                <span className="rhizome-settings-note">
                  Feed reasoning traces back into subsequent context. Uses significant tokens.
                </span>
              </div>
            )}

            <div className="rhizome-settings-field">
              <label>Debug: context limit override (tokens)</label>
              <input
                type="number"
                min="0"
                step="100"
                value={debugContextLimit}
                onChange={(e) => setDebugContextLimit(e.target.value)}
                placeholder="Use real model limit"
              />
              {debugContextLimit && parseInt(debugContextLimit, 10) > 0 && (
                <span className="rhizome-settings-note" style={{ color: 'var(--ctx-yellow)' }}>
                  Context limited to {parseInt(debugContextLimit, 10).toLocaleString()} tokens for testing
                </span>
              )}
            </div>

            {generationMode === 'chat' && (
              <>
                <div className="rhizome-settings-divider" />

                <div className="rhizome-settings-section-label">Context eviction</div>

                <div className="rhizome-settings-field">
                  <label>Eviction mode</label>
                  <select
                    value={evictionMode}
                    onChange={(e) => setEvictionMode(e.target.value as 'smart' | 'truncate' | 'none')}
                  >
                    <option value="smart">Smart (protect first/last/anchored)</option>
                    <option value="truncate">Truncate (oldest first)</option>
                    <option value="none">None (send everything)</option>
                  </select>
                </div>

                {evictionMode === 'smart' && (
                  <>
                    <div className="rhizome-settings-row-pair">
                      <div className="rhizome-settings-field">
                        <label>Keep first turns</label>
                        <input
                          type="number"
                          min="0"
                          step="1"
                          value={keepFirstTurns}
                          onChange={(e) => setKeepFirstTurns(e.target.value)}
                        />
                      </div>
                      <div className="rhizome-settings-field">
                        <label>Keep recent turns</label>
                        <input
                          type="number"
                          min="0"
                          step="1"
                          value={recentTurnsToKeep}
                          onChange={(e) => setRecentTurnsToKeep(e.target.value)}
                        />
                      </div>
                    </div>

                    <div className="rhizome-settings-field">
                      <label>Warning threshold</label>
                      <input
                        type="number"
                        min="0"
                        max="1"
                        step="0.05"
                        value={warnThreshold}
                        onChange={(e) => setWarnThreshold(e.target.value)}
                      />
                      <span className="rhizome-settings-note">
                        Warn when context reaches this fraction of the limit
                      </span>
                    </div>

                    <div className="rhizome-settings-toggle">
                      <label>
                        <input
                          type="checkbox"
                          checked={keepAnchored}
                          onChange={(e) => setKeepAnchored(e.target.checked)}
                        />
                        Protect anchored messages
                      </label>
                    </div>

                    <div className="rhizome-settings-toggle">
                      <label>
                        <input
                          type="checkbox"
                          checked={summarizeEvicted}
                          onChange={(e) => setSummarizeEvicted(e.target.checked)}
                        />
                        Summarize evicted messages
                      </label>
                      <span className="rhizome-settings-note">
                        Generate a recap of evicted content using a small model
                      </span>
                    </div>
                  </>
                )}
              </>
            )}

            <div className="rhizome-settings-divider" />

            <div className="rhizome-settings-section-label">Export</div>

            <div className="rhizome-settings-export-buttons">
              <button
                className="rhizome-settings-export-btn"
                onClick={() => exportRhizome(currentRhizome.rhizome_id, 'json')}
              >
                Export JSON
              </button>
              <button
                className="rhizome-settings-export-btn"
                onClick={() => exportRhizome(currentRhizome.rhizome_id, 'csv')}
              >
                Export CSV
              </button>
              <button
                className="rhizome-settings-export-btn"
                onClick={() => exportRhizome(currentRhizome.rhizome_id, 'json', true)}
              >
                Export JSON (with events)
              </button>
            </div>

            <div className="rhizome-settings-actions">
              {hasChanges && (
                <span className="rhizome-settings-dirty">Unsaved changes</span>
              )}
              <button
                className="rhizome-settings-save"
                onClick={handleSave}
                disabled={!hasChanges}
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
