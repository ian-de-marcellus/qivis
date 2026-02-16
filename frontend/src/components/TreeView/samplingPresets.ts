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

export const SAMPLING_PRESETS: Record<string, PresetValues> = {
  deterministic: { label: 'Deterministic', temperature: 0, top_p: 1 },
  balanced: { label: 'Balanced', temperature: 0.7 },
  creative: { label: 'Creative', temperature: 1.0, top_p: 0.95 },
}

export type PresetName = keyof typeof SAMPLING_PRESETS | 'custom'

/**
 * Detect which preset matches the current sampling state, if any.
 * Returns 'custom' if no preset matches.
 */
export function detectPreset(temperature: string, topP: string): PresetName {
  const temp = temperature ? parseFloat(temperature) : undefined
  const tp = topP ? parseFloat(topP) : undefined

  for (const [name, preset] of Object.entries(SAMPLING_PRESETS)) {
    const tempMatch = preset.temperature === undefined
      ? temp === undefined
      : temp === preset.temperature
    const tpMatch = preset.top_p === undefined
      ? tp === undefined
      : tp === preset.top_p
    if (tempMatch && tpMatch) return name as PresetName
  }
  return 'custom'
}
