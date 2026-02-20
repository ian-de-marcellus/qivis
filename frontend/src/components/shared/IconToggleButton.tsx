import type { ReactNode } from 'react'
import './IconToggleButton.css'

interface IconToggleButtonProps {
  active: boolean
  onClick: () => void
  activeLabel: string
  inactiveLabel: string
  title?: string
  className?: string
  children: ReactNode
}

export function IconToggleButton({
  active,
  onClick,
  activeLabel,
  inactiveLabel,
  title,
  className,
  children,
}: IconToggleButtonProps) {
  return (
    <button
      className={`icon-toggle-btn ${active ? 'active' : ''}${className ? ` ${className}` : ''}`}
      onClick={onClick}
      aria-label={active ? activeLabel : inactiveLabel}
      title={title}
    >
      {children}
    </button>
  )
}
