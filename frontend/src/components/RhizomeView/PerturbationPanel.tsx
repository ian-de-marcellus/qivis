import { useEffect, useRef, useState } from 'react'
import type { DigressionGroupResponse, PerturbationConfig, ProviderInfo, SamplingParams } from '../../api/types.ts'
import { useRhizomeStore } from '../../store/rhizomeStore.ts'
import './ForkPanel.css'

interface PerturbationPanelProps {
  nodeId: string
  onCancel: () => void
  providers: ProviderInfo[]
  digressionGroups: DigressionGroupResponse[]
  defaults: {
    provider: string | null
    model: string | null
    systemPrompt: string | null
  }
}

const PERTURBATION_TYPES = [
  { value: 'digression_toggle', label: 'Toggle digression group' },
  { value: 'node_exclusion', label: 'Toggle node exclusion' },
  { value: 'system_prompt', label: 'Swap system prompt' },
  { value: 'intervention_toggle', label: 'Toggle intervention' },
] as const

export function PerturbationPanel({
  nodeId,
  onCancel,
  providers,
  digressionGroups,
  defaults,
}: PerturbationPanelProps) {
  const runPerturbation = useRhizomeStore(s => s.runPerturbation)
  const perturbationState = useRhizomeStore(s => s.perturbationState)
  const stopGeneration = useRhizomeStore(s => s.stopGeneration)

  const defaultProvider =
    providers.find((p) => p.name === defaults.provider)?.name ??
    providers[0]?.name ??
    ''
  const [provider, setProvider] = useState(defaultProvider)
  const [model, setModel] = useState(defaults.model ?? '')
  const [includeControl, setIncludeControl] = useState(true)
  const [configs, setConfigs] = useState<PerturbationConfig[]>([
    { type: 'system_prompt', system_prompt: '' },
  ])

  const selectedProvider = providers.find((p) => p.name === provider)
  const suggestedModels = selectedProvider?.models ?? []

  const panelRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    panelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [])

  const isActive = perturbationState?.active ?? false
  const step = perturbationState?.step ?? 0
  const total = perturbationState?.total ?? 0
  const currentLabel = perturbationState?.currentLabel ?? ''
  const stepContents = perturbationState?.stepContents ?? {}

  const addConfig = () => {
    setConfigs([...configs, { type: 'system_prompt', system_prompt: '' }])
  }

  const removeConfig = (index: number) => {
    setConfigs(configs.filter((_, i) => i !== index))
  }

  const updateConfig = (index: number, updates: Partial<PerturbationConfig>) => {
    setConfigs(configs.map((c, i) => i === index ? { ...c, ...updates } : c))
  }

  const handleLaunch = () => {
    if (isActive || configs.length === 0) return
    const samplingParams: SamplingParams | undefined = undefined
    runPerturbation(
      nodeId,
      configs,
      provider,
      model || undefined,
      samplingParams,
      includeControl,
    )
  }

  // Compute latest streaming text across steps
  const latestStepIdx = Object.keys(stepContents).length > 0
    ? Math.max(...Object.keys(stepContents).map(Number))
    : -1
  const latestText = latestStepIdx >= 0 ? stepContents[latestStepIdx] ?? '' : ''

  return (
    <div className="fork-panel" ref={panelRef}>
      <div className="fork-panel-header">
        <span className="fork-panel-title">Perturbation experiment</span>
        <button className="fork-panel-close" onClick={isActive ? stopGeneration : onCancel}>
          {isActive ? 'Stop' : 'Cancel'}
        </button>
      </div>

      <div className="fork-panel-body">
        {isActive ? (
          <div style={{ padding: '0.5rem 0' }}>
            <div style={{ marginBottom: '0.4rem', fontSize: '0.82rem' }}>
              Step {step} of {total}
              {currentLabel && (
                <span style={{ marginLeft: '0.5rem', color: 'var(--text-secondary)' }}>
                  {currentLabel}
                </span>
              )}
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
            {latestText && (
              <div style={{
                fontSize: '0.8rem',
                color: 'var(--text-secondary)',
                maxHeight: '80px',
                overflow: 'hidden',
                whiteSpace: 'pre-wrap',
              }}>
                {latestText.slice(-200)}
              </div>
            )}
          </div>
        ) : (
          <>
            <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
              Generate responses with systematically modified context,
              then measure divergence from a control response.
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
                list="perturb-model-suggestions"
              />
              <datalist id="perturb-model-suggestions">
                {suggestedModels.map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            </div>

            <div className="fork-setting-row">
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={includeControl}
                  onChange={(e) => setIncludeControl(e.target.checked)}
                />
                Include control (baseline)
              </label>
            </div>

            <div style={{ margin: '0.75rem 0 0.25rem', fontSize: '0.82rem', fontWeight: 600 }}>
              Perturbations
            </div>

            {configs.map((config, i) => (
              <PerturbationConfigRow
                key={i}
                config={config}
                digressionGroups={digressionGroups}
                onChange={(updates) => updateConfig(i, updates)}
                onRemove={configs.length > 1 ? () => removeConfig(i) : undefined}
              />
            ))}

            {configs.length < 20 && (
              <button
                style={{
                  fontSize: '0.78rem',
                  color: 'var(--accent-primary)',
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                  padding: '0.25rem 0',
                }}
                onClick={addConfig}
              >
                + Add perturbation
              </button>
            )}

            <button
              className="fork-submit-btn"
              onClick={handleLaunch}
              disabled={!provider || configs.length === 0}
              style={{ marginTop: '0.75rem' }}
            >
              Run experiment ({includeControl ? configs.length + 1 : configs.length} generations)
            </button>
          </>
        )}
      </div>
    </div>
  )
}

function PerturbationConfigRow({
  config,
  digressionGroups,
  onChange,
  onRemove,
}: {
  config: PerturbationConfig
  digressionGroups: DigressionGroupResponse[]
  onChange: (updates: Partial<PerturbationConfig>) => void
  onRemove?: () => void
}) {
  return (
    <div style={{
      padding: '0.5rem',
      marginBottom: '0.5rem',
      border: '1px solid var(--border-color)',
      borderRadius: '6px',
      background: 'var(--bg-secondary)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem' }}>
        <select
          value={config.type}
          onChange={(e) => onChange({ type: e.target.value as PerturbationConfig['type'] })}
          style={{ flex: 1, fontSize: '0.8rem' }}
        >
          {PERTURBATION_TYPES.map((t) => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>
        {onRemove && (
          <button
            onClick={onRemove}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)', fontSize: '0.9rem' }}
          >
            &times;
          </button>
        )}
      </div>

      {config.type === 'system_prompt' && (
        <div>
          <textarea
            value={config.system_prompt ?? ''}
            onChange={(e) => onChange({ system_prompt: e.target.value })}
            rows={2}
            placeholder="Replacement system prompt..."
            style={{ width: '100%', fontSize: '0.8rem', resize: 'vertical' }}
          />
          <input
            type="text"
            value={config.label ?? ''}
            onChange={(e) => onChange({ label: e.target.value || undefined })}
            placeholder="Label (auto-generated if blank)"
            style={{ width: '100%', fontSize: '0.78rem', marginTop: '0.25rem' }}
          />
        </div>
      )}

      {config.type === 'digression_toggle' && (
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', fontSize: '0.8rem' }}>
          <select
            value={config.group_id ?? ''}
            onChange={(e) => onChange({ group_id: e.target.value || undefined })}
            style={{ flex: 1 }}
          >
            <option value="">Select group...</option>
            {digressionGroups.map((g) => (
              <option key={g.group_id} value={g.group_id}>{g.label}</option>
            ))}
          </select>
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={config.include ?? false}
              onChange={(e) => onChange({ include: e.target.checked })}
            />
            Include
          </label>
        </div>
      )}

      {config.type === 'node_exclusion' && (
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', fontSize: '0.8rem' }}>
          <input
            type="text"
            value={config.node_id ?? ''}
            onChange={(e) => onChange({ node_id: e.target.value || undefined })}
            placeholder="Node ID to toggle"
            style={{ flex: 1 }}
          />
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={config.exclude ?? true}
              onChange={(e) => onChange({ exclude: e.target.checked })}
            />
            Exclude
          </label>
        </div>
      )}

      {config.type === 'intervention_toggle' && (
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', fontSize: '0.8rem' }}>
          <input
            type="number"
            value={config.intervention_index ?? 0}
            onChange={(e) => onChange({ intervention_index: parseInt(e.target.value) || 0 })}
            placeholder="Intervention index"
            style={{ width: '80px' }}
            min={0}
          />
          <label style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={config.enabled ?? true}
              onChange={(e) => onChange({ enabled: e.target.checked })}
            />
            Enabled
          </label>
        </div>
      )}
    </div>
  )
}
