import { useEffect, useRef, useState } from 'react'
import type { CrossModelTarget, ProviderInfo } from '../../api/types.ts'
import { useRhizomeStore } from '../../store/rhizomeStore.ts'
import './ForkPanel.css'

interface CrossModelPanelProps {
  nodeId: string
  onCancel: () => void
  isGenerating: boolean
  providers: ProviderInfo[]
  defaults: {
    provider: string | null
    model: string | null
  }
}

export function CrossModelPanel({
  nodeId,
  onCancel,
  isGenerating,
  providers,
}: CrossModelPanelProps) {
  const generateCrossModel = useRhizomeStore(s => s.generateCrossModel)

  // Start with one empty target row
  const [targets, setTargets] = useState<CrossModelTarget[]>(() => {
    const firstProvider = providers[0]?.name ?? ''
    const firstModel = providers[0]?.models?.[0] ?? ''
    return [{ provider: firstProvider, model: firstModel }]
  })

  const panelRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    panelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [])

  const addTarget = () => {
    if (targets.length >= 10) return
    // Pick a provider not yet used, or fall back to first
    const usedProviders = new Set(targets.map(t => t.provider))
    const nextProvider = providers.find(p => !usedProviders.has(p.name))
      ?? providers[0]
    setTargets([...targets, {
      provider: nextProvider?.name ?? '',
      model: nextProvider?.models?.[0] ?? '',
    }])
  }

  const removeTarget = (index: number) => {
    if (targets.length <= 1) return
    setTargets(targets.filter((_, i) => i !== index))
  }

  const updateTarget = (index: number, field: keyof CrossModelTarget, value: string) => {
    setTargets(targets.map((t, i) => {
      if (i !== index) return t
      if (field === 'provider') {
        // Reset model when provider changes
        const providerInfo = providers.find(p => p.name === value)
        return { ...t, provider: value, model: providerInfo?.models?.[0] ?? '' }
      }
      return { ...t, [field]: value }
    }))
  }

  const canSubmit = targets.length > 0
    && targets.every(t => t.provider && t.model)
    && !isGenerating

  const handleSubmit = () => {
    if (!canSubmit) return
    generateCrossModel(nodeId, targets)
    onCancel()
  }

  return (
    <div className="fork-panel" ref={panelRef}>
      <div className="fork-panel-header">
        <span className="fork-panel-title">Compare across models</span>
        <button className="fork-panel-close" onClick={onCancel}>Cancel</button>
      </div>

      <div className="fork-panel-body">
        <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
          Generate from this node with multiple models simultaneously
        </div>

        {targets.map((target, index) => {
          const providerInfo = providers.find(p => p.name === target.provider)
          const suggestedModels = providerInfo?.models ?? []
          return (
            <div key={index} style={{
              display: 'flex', gap: '0.4rem', alignItems: 'center',
              marginBottom: '0.4rem',
            }}>
              <select
                value={target.provider}
                onChange={(e) => updateTarget(index, 'provider', e.target.value)}
                style={{ flex: '0 0 auto', minWidth: '100px' }}
              >
                {providers.map((p) => (
                  <option key={p.name} value={p.name}>{p.name}</option>
                ))}
              </select>
              <input
                type="text"
                value={target.model}
                onChange={(e) => updateTarget(index, 'model', e.target.value)}
                placeholder={suggestedModels[0] ?? 'model'}
                list={`cross-model-${index}`}
                style={{ flex: 1, minWidth: 0 }}
              />
              <datalist id={`cross-model-${index}`}>
                {suggestedModels.map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
              {targets.length > 1 && (
                <button
                  className="fork-panel-close"
                  onClick={() => removeTarget(index)}
                  style={{ padding: '0 0.3rem', fontSize: '0.75rem' }}
                >
                  x
                </button>
              )}
            </div>
          )
        })}

        {targets.length < 10 && (
          <button
            className="fork-settings-toggle"
            onClick={addTarget}
            style={{ marginBottom: '0.5rem' }}
          >
            + Add model
          </button>
        )}

        <button
          className="fork-submit-btn"
          onClick={handleSubmit}
          disabled={!canSubmit}
        >
          {isGenerating ? 'Generating...' : `Generate (${targets.length} model${targets.length > 1 ? 's' : ''})`}
        </button>
      </div>
    </div>
  )
}
