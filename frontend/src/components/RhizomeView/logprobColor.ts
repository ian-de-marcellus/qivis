/** Token certainty, as numbers and as the heatmap's colors. */

import type { LogprobData } from '../../api/types.ts'

/**
 * Maps linear probability to an HSLA background color.
 * High confidence (>0.95) is transparent — no visual noise.
 * Low confidence gets a warm highlight anchored to sienna (~20 hue).
 */
export function uncertaintyColor(linearProb: number): string {
  if (linearProb >= 0.95) return 'transparent'

  // Uncertainty as 0..1 scale (inverted from probability)
  const u = 1 - linearProb

  // Non-linear ramp: sqrt pushes faint highlights further into the visible range
  const intensity = Math.sqrt(u)

  // Warm sienna hue (~20), saturation scales with uncertainty
  const saturation = 40 + intensity * 50 // 40% → 90%
  const lightness = 55 - intensity * 10 // 55% → 45%
  const alpha = intensity * 0.45 // 0 → 0.45

  return `hsla(20, ${saturation}%, ${lightness}%, ${alpha})`
}

export function averageCertainty(logprobs: LogprobData): number {
  if (logprobs.tokens.length === 0) return 1
  const sum = logprobs.tokens.reduce((acc, t) => acc + t.linear_prob, 0)
  return sum / logprobs.tokens.length
}
