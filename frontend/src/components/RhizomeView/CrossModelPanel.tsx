import { useEffect, useRef, useState } from 'react'
import type { CrossModelTarget, ProviderInfo } from '../../api/types.ts'
import { useRhizomeData, useRhizomeStore } from '../../store/rhizomeStore.ts'
import { ModelPicker } from '../shared/ModelPicker.tsx'
import { findModel, type ModelChoice } from '../shared/modelChoice.ts'
import { type GenerationModeChoice, effectiveMode } from './generationMode.ts'
import { ModeSelect } from './ModeSelect.tsx'
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

interface Row extends ModelChoice {
  mode: GenerationModeChoice
}

export function CrossModelPanel({
  nodeId,
  onCancel,
  isGenerating,
  providers,
  defaults,
}: CrossModelPanelProps) {
  const generateCrossModel = useRhizomeStore(s => s.generateCrossModel)
  const { models } = useRhizomeData()

  // Start from the branch's model; add more to compare against it
  const [rows, setRows] = useState<Row[]>(() => [{
    provider: providers.find((p) => p.name === defaults.provider)?.name ?? providers[0]?.name ?? '',
    model: defaults.model ?? '',
    mode: '',
  }])

  const panelRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    panelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [])

  const addRow = () => {
    if (rows.length >= 10) return
    const used = new Set(rows.map(r => `${r.provider}:${r.model}`))
    const next = models.find(m => !used.has(m.id))
    setRows([...rows, { provider: next?.provider ?? '', model: next?.model ?? '', mode: '' }])
  }

  const update = (i: number, patch: Partial<Row>) =>
    setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)))

  const canSubmit = rows.length > 0 && rows.every(r => r.provider && r.model) && !isGenerating

  const handleSubmit = () => {
    if (!canSubmit) return
    const targets: CrossModelTarget[] = rows.map((r) => {
      const provider = providers.find(p => p.name === r.provider)
      // Each target runs in its own model's mode (e.g. GPT → chat inside a Sun rhizome)
      const mode = effectiveMode(provider, r.mode || findModel(models, r)?.mode || '')
      return { provider: r.provider, model: r.model, ...(mode && { mode }) }
    })
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
          Generate from this node with several models at once; each uses its own format
        </div>

        {rows.map((row, i) => (
          <div key={i} className="cross-model-row">
            <ModelPicker
              value={row}
              onChange={(v) => update(i, { ...v, mode: '' })}
              models={models}
              providers={providers}
            />
            <ModeSelect
              provider={providers.find(p => p.name === row.provider)}
              value={row.mode}
              onChange={(mode) => update(i, { mode })}
              row={false}
              modelMode={findModel(models, row)?.mode}
            />
            {rows.length > 1 && (
              <button
                className="fork-panel-close"
                onClick={() => setRows(rows.filter((_, j) => j !== i))}
                aria-label="Remove model"
              >
                x
              </button>
            )}
          </div>
        ))}

        {rows.length < 10 && (
          <button className="fork-settings-toggle" onClick={addRow} style={{ marginBottom: '0.5rem' }}>
            + Add model
          </button>
        )}

        <button className="fork-submit-btn" onClick={handleSubmit} disabled={!canSubmit}>
          {isGenerating ? 'Generating...' : `Generate (${rows.length} model${rows.length > 1 ? 's' : ''})`}
        </button>
      </div>
    </div>
  )
}
