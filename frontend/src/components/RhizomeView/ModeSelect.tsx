import type { ProviderInfo } from '../../api/types.ts'
import { useRhizomeData } from '../../store/rhizomeStore.ts'
import { type GenerationModeChoice, isDualMode } from './generationMode.ts'

interface ModeSelectProps {
  provider: ProviderInfo | undefined
  value: GenerationModeChoice
  onChange: (value: GenerationModeChoice) => void
  /** Render as a labeled settings row (true) or a bare select (false). */
  row?: boolean
  /** The chosen model's own mode, used when no override is set. */
  modelMode?: 'chat' | 'completion'
}

/**
 * Chat/completion override for providers that support both. E.g. GPT or
 * Llama-Instruct inside a completion-mode (Sun) rhizome needs chat; a base
 * model on the same provider wants completion. Hidden for single-mode
 * providers, which have no choice to make.
 */
export function ModeSelect({ provider, value, onChange, row = true, modelMode }: ModeSelectProps) {
  const { currentRhizome } = useRhizomeData()
  // What a dual-mode provider does when no override is set: the model's own
  // mode if known, else the rhizome's
  const rhizomeMode = currentRhizome?.metadata?.generation_mode === 'completion' ? 'completion' : 'chat'
  const fallback = modelMode ? `From model (${modelMode})` : `Rhizome default (${rhizomeMode})`
  if (!isDualMode(provider)) return null

  const select = (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as GenerationModeChoice)}
      title="Chat sends messages; completion sends a rendered prompt (for base models)"
      style={row ? undefined : { flex: '0 0 auto' }}
    >
      <option value="">{fallback}</option>
      <option value="chat">Chat</option>
      <option value="completion">Completion</option>
    </select>
  )
  if (!row) return select
  return (
    <div className="fork-setting-row">
      <label>Mode</label>
      {select}
    </div>
  )
}
