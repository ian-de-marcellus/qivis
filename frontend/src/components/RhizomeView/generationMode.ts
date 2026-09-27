import type { ProviderInfo } from '../../api/types.ts'

export type GenerationModeChoice = '' | 'chat' | 'completion'

export function isDualMode(provider: ProviderInfo | undefined): boolean {
  const modes = provider?.supported_modes ?? []
  return modes.includes('chat') && modes.includes('completion')
}

/**
 * The mode override to send: only for providers that support both modes.
 * A choice left over from a previously selected provider is dropped, since
 * single-mode providers reject an explicit mode they don't support.
 */
export function effectiveMode(
  provider: ProviderInfo | undefined,
  choice: GenerationModeChoice,
): 'chat' | 'completion' | undefined {
  return choice && isDualMode(provider) ? choice : undefined
}
