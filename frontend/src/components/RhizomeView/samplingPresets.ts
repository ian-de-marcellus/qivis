/** Named sampling presets for quick configuration. */

export interface PresetValues {
  label: string
  temperature?: number
  top_p?: number
  top_k?: number
  max_tokens?: number
  frequency_penalty?: number
  presence_penalty?: number
}

/** "default" leaves everything unset, so the model's own defaults apply. */
export const SAMPLING_PRESETS: Record<string, PresetValues> = {
  default: { label: 'Model default' },
  deterministic: { label: 'Deterministic', temperature: 0, top_p: 1 },
  balanced: { label: 'Balanced', temperature: 0.7 },
  creative: { label: 'Creative', temperature: 1.0, top_p: 0.95 },
}

export type PresetName = keyof typeof SAMPLING_PRESETS | 'custom'

/** The fields a preset sets (all of them: a preset leaves nothing stale behind). */
export const PRESET_FIELDS = [
  ['temperature', 'temperature'],
  ['topP', 'top_p'],
  ['topK', 'top_k'],
  ['frequencyPenalty', 'frequency_penalty'],
  ['presencePenalty', 'presence_penalty'],
] as const

type FieldValues = Record<(typeof PRESET_FIELDS)[number][0], string>

/**
 * Detect which preset matches the current sampling state, if any.
 * Returns 'custom' if no preset matches. (Max tokens isn't part of a preset.)
 */
export function detectPreset(values: FieldValues): PresetName {
  for (const [name, preset] of Object.entries(SAMPLING_PRESETS)) {
    const matches = PRESET_FIELDS.every(([field, key]) => {
      const v = values[field] ? parseFloat(values[field]) : undefined
      return v === preset[key]
    })
    if (matches) return name as PresetName
  }
  return 'custom'
}
