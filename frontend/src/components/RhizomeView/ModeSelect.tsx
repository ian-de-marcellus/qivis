import type { ProviderInfo } from '../../api/types.ts'
import { useRhizomeData } from '../../store/rhizomeStore.ts'
import { type GenerationModeChoice, isDualMode } from './generationMode.ts'

interface ModeSelectProps {
  provider: ProviderInfo | undefined
  value: GenerationModeChoice
  onChange: (value: GenerationModeChoice) => void
  /** Render as a labeled settings row (true) or a bare select (false). */
  row?: boolean
}

/**
 * Chat/completion override for providers that support both. E.g. GPT or
 * Llama-Instruct inside a completion-mode (Sun) rhizome needs chat; a base
 * model on the same provider wants completion. Hidden for single-mode
 * providers, which have no choice to make.
 */
export function ModeSelect({ provider, value, onChange, row = true }: ModeSelectProps) {
  const { currentRhizome } = useRhizomeData()
  // What a dual-mode provider does when no override is set
  const rhizomeMode = currentRhizome?.metadata?.generation_mode === 'completion' ? 'completion' : 'chat'
  if (!isDualMode(provider)) return null

  const select = (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as GenerationModeChoice)}
      title="Chat sends messages; completion sends a rendered prompt (for base models)"
      style={row ? undefined : { flex: '0 0 auto' }}
    >
      <option value="">{`Rhizome default (${rhizomeMode})`}</option>
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
