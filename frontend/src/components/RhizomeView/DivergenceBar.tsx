interface DivergenceBarProps {
  value: number
  label?: string
  /** If true, bar is centered at 0 and extends left (negative) or right (positive). Range: -1..1 */
  centered?: boolean
}

function divergenceColor(value: number): string {
  // 0 = green, 0.5 = yellow, 1 = red
  const t = Math.min(Math.max(value, 0), 1)
  if (t < 0.5) {
    // green to yellow
    const r = Math.round(200 * (t / 0.5))
    const g = 180
    return `rgb(${r}, ${g}, 80)`
  }
  // yellow to red
  const r = 200
  const g = Math.round(180 * (1 - (t - 0.5) / 0.5))
  return `rgb(${r}, ${g}, 60)`
}

export function DivergenceBar({ value, label, centered }: DivergenceBarProps) {
  if (centered) {
    const clamped = Math.min(Math.max(value, -1), 1)
    const pct = Math.abs(clamped) * 50
    const isNegative = clamped < 0
    const color = divergenceColor(Math.abs(clamped))

    return (
      <div className="divergence-bar-row">
        {label && <span className="divergence-bar-label">{label}</span>}
        <div className="divergence-bar-track centered" style={{ position: 'relative', height: 8, flex: 1, background: 'var(--border-color)', borderRadius: 4 }}>
          <div style={{
            position: 'absolute',
            top: 0,
            height: '100%',
            width: `${pct}%`,
            left: isNegative ? `${50 - pct}%` : '50%',
            background: color,
            borderRadius: 4,
            transition: 'width 0.3s ease, left 0.3s ease',
          }} />
          <div style={{
            position: 'absolute',
            top: -1,
            left: '50%',
            width: 1,
            height: 10,
            background: 'var(--text-secondary)',
          }} />
        </div>
        <span className="divergence-bar-value">{value > 0 ? '+' : ''}{value.toFixed(2)}</span>
      </div>
    )
  }

  const clamped = Math.min(Math.max(value, 0), 1)
  const pct = clamped * 100
  const color = divergenceColor(clamped)

  return (
    <div className="divergence-bar-row">
      {label && <span className="divergence-bar-label">{label}</span>}
      <div style={{ position: 'relative', height: 8, flex: 1, background: 'var(--border-color)', borderRadius: 4 }}>
        <div style={{
          width: `${pct}%`,
          height: '100%',
          background: color,
          borderRadius: 4,
          transition: 'width 0.3s ease',
        }} />
      </div>
      <span className="divergence-bar-value">{clamped.toFixed(2)}</span>
    </div>
  )
}
