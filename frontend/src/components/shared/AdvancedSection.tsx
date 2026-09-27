import { type ReactNode, useState } from 'react'
import './AdvancedSection.css'

interface AdvancedSectionProps {
  /** Remembers open/closed per panel (localStorage key suffix). */
  storageKey: string
  label?: string
  /** Short hint shown next to the label when collapsed, e.g. "Format · Sampling · Context". */
  summary?: string
  children: ReactNode
}

function readOpen(key: string): boolean {
  try { return localStorage.getItem(`qivis-advanced-${key}`) === '1' } catch { return false }
}

/** The one "Advanced" disclosure used by every settings panel. */
export function AdvancedSection({ storageKey, label = 'Advanced', summary, children }: AdvancedSectionProps) {
  const [open, setOpen] = useState(() => readOpen(storageKey))
  const toggle = () => {
    const next = !open
    setOpen(next)
    try { localStorage.setItem(`qivis-advanced-${storageKey}`, next ? '1' : '0') } catch { /* private mode */ }
  }
  return (
    <div className="advanced-section">
      <button type="button" className="advanced-toggle" onClick={toggle} aria-expanded={open}>
        <span className={`toggle-arrow ${open ? 'expanded' : ''}`}>&#9654;</span>
        {label}
        {!open && summary && <span className="advanced-summary">{summary}</span>}
      </button>
      {open && <div className="advanced-body">{children}</div>}
    </div>
  )
}

/** A labeled group inside an AdvancedSection. */
export function AdvancedGroup({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="advanced-group">
      <h4 className="advanced-group-title">{title}</h4>
      {children}
    </section>
  )
}
