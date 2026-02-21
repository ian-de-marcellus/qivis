/**
 * Deterministic tag color: same name always maps to the same hue.
 * Muted palette that works across light/dark themes.
 */

const TAG_PALETTE = [
  '#8b7355', '#6b8e6b', '#7b8fad', '#ad7b7b',
  '#9b8fad', '#ad9b7b', '#7bad8f', '#8f7bad',
  '#ad8f7b', '#7b8bad', '#8bad7b', '#ad7bad',
]

export function tagColor(name: string): string {
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = ((hash << 5) - hash) + name.charCodeAt(i)
    hash |= 0
  }
  return TAG_PALETTE[Math.abs(hash) % TAG_PALETTE.length]
}
