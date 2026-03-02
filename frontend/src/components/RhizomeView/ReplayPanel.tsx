import { useEffect, useRef, useState } from 'react'
import type { ProviderInfo, SamplingParams } from '../../api/types.ts'
import { useRhizomeStore } from '../../store/rhizomeStore.ts'
import './ForkPanel.css'

interface ReplayPanelProps {
  pathNodeIds: string[]
  pathDescription: string
  onCancel: () => void
  providers: ProviderInfo[]
  defaults: {
    provider: string | null
    model: string | null
    systemPrompt: string | null
  }
}

export function ReplayPanel({
  pathNodeIds,
  pathDescription,
  onCancel,
  providers,
  defaults,
}: ReplayPanelProps) {
  const startReplay = useRhizomeStore(s => s.startReplay)
  const replayState = useRhizomeStore(s => s.replayState)
  const stopGeneration = useRhizomeStore(s => s.stopGeneration)

  const defaultProvider =
    providers.find((p) => p.name === defaults.provider)?.name ??
    providers[0]?.name ??
    ''
  const [provider, setProvider] = useState(defaultProvider)
  const [model, setModel] = useState(defaults.model ?? '')
  const [mode, setMode] = useState<'context_faithful' | 'trajectory'>('context_faithful')
  const [systemPrompt, setSystemPrompt] = useState(defaults.systemPrompt ?? '')
  const [showSettings, setShowSettings] = useState(false)

  const selectedProvider = providers.find((p) => p.name === provider)
  const suggestedModels = selectedProvider?.models ?? []

  const panelRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    panelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [])

  const isActive = replayState?.active ?? false
  const step = replayState?.step ?? 0
  const total = replayState?.total ?? pathNodeIds.length
  const streamingText = replayState?.streamingText ?? ''

  const handleLaunch = () => {
    if (isActive) return
    const samplingParams: SamplingParams | undefined = undefined
    startReplay(
      pathNodeIds,
      provider,
      model || undefined,
      mode,
      systemPrompt || undefined,
      samplingParams,
    )
  }

  const assistantCount = Math.ceil(pathNodeIds.length / 2)

  return (
    <div className="fork-panel" ref={panelRef}>
      <div className="fork-panel-header">
        <span className="fork-panel-title">Replay conversation</span>
        <button className="fork-panel-close" onClick={isActive ? stopGeneration : onCancel}>
          {isActive ? 'Stop' : 'Cancel'}
        </button>
      </div>

      <div className="fork-panel-body">
        <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
          {pathDescription} ({pathNodeIds.length} messages, {assistantCount} to regenerate)
        </div>

        {isActive ? (
          <div style={{ padding: '0.5rem 0' }}>
            <div style={{ marginBottom: '0.4rem', fontSize: '0.82rem' }}>
              Step {step} of {total}
              {step > 0 && (
                <span style={{
                  display: 'inline-block',
                  marginLeft: '0.5rem',
                  width: '100px',
                  height: '4px',
                  background: 'var(--border-color)',
                  borderRadius: '2px',
                  verticalAlign: 'middle',
                }}>
                  <span style={{
                    display: 'block',
                    width: `${(step / total) * 100}%`,
                    height: '100%',
                    background: 'var(--accent-primary)',
                    borderRadius: '2px',
                    transition: 'width 0.3s ease',
                  }} />
                </span>
              )}
            </div>
            {streamingText && (
              <div style={{
                fontSize: '0.8rem',
                color: 'var(--text-secondary)',
                maxHeight: '80px',
                overflow: 'hidden',
                whiteSpace: 'pre-wrap',
              }}>
                {streamingText.slice(-200)}
              </div>
            )}
          </div>
        ) : (
          <>
            <div className="fork-setting-row">
              <label>Mode</label>
              <select value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
                <option value="context_faithful">Context-faithful</option>
                <option value="trajectory">Trajectory</option>
              </select>
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
              {mode === 'context_faithful'
                ? 'Model sees original assistant messages at each step'
                : 'Model builds on its own prior responses'}
            </div>

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
                    <option key={p.name} value={p.name}>{p.name}</option>
                  ))}
                </select>
              ) : (
                <select disabled><option>No providers available</option></select>
              )}
            </div>
            <div className="fork-setting-row">
              <label>Model</label>
              <input
                type="text"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder={suggestedModels[0] ?? 'default'}
                list="replay-model-suggestions"
              />
              <datalist id="replay-model-suggestions">
                {suggestedModels.map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            </div>

            <button
              className="fork-settings-toggle"
              onClick={() => setShowSettings(!showSettings)}
            >
              <span className={`toggle-arrow ${showSettings ? 'expanded' : ''}`}>
                &#9654;
              </span>
              System prompt override
            </button>

            {showSettings && (
              <div className="fork-settings">
                <div className="fork-setting-row">
                  <textarea
                    value={systemPrompt}
                    onChange={(e) => setSystemPrompt(e.target.value)}
                    rows={2}
                    placeholder="Override system prompt..."
                  />
                </div>
              </div>
            )}

            <button
              className="fork-submit-btn"
              onClick={handleLaunch}
              disabled={!provider}
            >
              Start replay
            </button>
          </>
        )}
      </div>
    </div>
  )
}
