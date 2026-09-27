import type { ModelEntry } from '../../api/types.ts'

export interface ModelChoice {
  provider: string
  model: string
}

/** The catalog entry for a choice, if it's a known model. */
export function findModel(models: ModelEntry[], v: ModelChoice): ModelEntry | undefined {
  return models.find((m) => m.provider === v.provider && m.model === v.model)
}

/** What a model brings: its mode and template, and where they come from. */
export function describeModel(entry: ModelEntry | undefined): string | null {
  if (!entry) return null
  const parts: string[] = [entry.mode]
  if (entry.mode === 'completion') parts.push(entry.prompt_template ?? 'raw template')
  parts.push(entry.source === 'profile' ? `from ${entry.label}'s profile` : entry.provider)
  return parts.join(' · ')
}
