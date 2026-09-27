import { useState } from 'react'
import type { ModelEntry, ProviderInfo } from '../../api/types.ts'
import { describeModel, findModel, type ModelChoice } from './modelChoice.ts'
import './ModelPicker.css'

const OTHER = '__other__'

interface ModelPickerProps {
  value: ModelChoice
  onChange: (value: ModelChoice) => void
  models: ModelEntry[]
  providers: ProviderInfo[]
  /** Offer an empty choice (e.g. a rhizome with no default model). */
  emptyLabel?: string
  /** Show the "completion · llama3 · from …" line under the select. */
  showDetails?: boolean
  id?: string
}

/**
 * One picker for "which model": named models first (with the defaults they
 * carry), then each provider's discovered models, plus "Other model…" for
 * anything unlisted.
 */
export function ModelPicker({
  value, onChange, models, providers, emptyLabel, showDetails = true, id,
}: ModelPickerProps) {
  const known = findModel(models, value)
  const [other, setOther] = useState(false)
  const isOther = other || (!known && !!value.model)
  const selected = isOther ? OTHER : known ? known.id : ''

  const profiled = models.filter((m) => m.source === 'profile')
  const byProvider = new Map<string, ModelEntry[]>()
  for (const m of models) {
    if (m.source === 'profile') continue
    byProvider.set(m.provider, [...(byProvider.get(m.provider) ?? []), m])
  }

  const pick = (id: string) => {
    if (id === OTHER) {
      setOther(true)
      onChange({ provider: value.provider || providers[0]?.name || '', model: '' })
      return
    }
    setOther(false)
    const m = models.find((e) => e.id === id)
    onChange(m ? { provider: m.provider, model: m.model } : { provider: '', model: '' })
  }

  const detail = showDetails ? describeModel(known) : null

  return (
    <div className="model-picker">
      <select id={id} value={selected} onChange={(e) => pick(e.target.value)}>
        {(emptyLabel != null || selected === '') && (
          <option value="">{emptyLabel ?? 'Choose a model…'}</option>
        )}
        {profiled.length > 0 && (
          <optgroup label="Your models">
            {profiled.map((m) => (
              <option key={m.id} value={m.id}>{m.label} ({m.provider})</option>
            ))}
          </optgroup>
        )}
        {[...byProvider.entries()].map(([provider, entries]) => (
          <optgroup key={provider} label={provider}>
            {entries.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </optgroup>
        ))}
        <option value={OTHER}>Other model…</option>
      </select>
      {isOther && (
        <div className="model-picker-other">
          <select
            value={value.provider}
            onChange={(e) => onChange({ provider: e.target.value, model: value.model })}
            aria-label="Provider"
          >
            {providers.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
          </select>
          <input
            type="text"
            value={value.model}
            placeholder="model name"
            onChange={(e) => onChange({ provider: value.provider, model: e.target.value })}
            aria-label="Model"
          />
        </div>
      )}
      {detail && <div className="model-picker-detail">{detail}</div>}
    </div>
  )
}
