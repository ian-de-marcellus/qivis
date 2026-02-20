import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import './ActionMenu.css'

interface ActionMenuProps {
  trigger: ReactNode
  triggerAriaLabel: string
  isActive?: boolean
  badge?: number
  children: ReactNode
  align?: 'left' | 'right'
  /** Extra class name on the outermost wrapper */
  className?: string
  /** Push this group to the right with margin-left: auto */
  pushRight?: boolean
}

export function ActionMenu({
  trigger, triggerAriaLabel, isActive, badge, children,
  align = 'left', className, pushRight,
}: ActionMenuProps) {
  const [open, setOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('pointerdown', handler)
    return () => document.removeEventListener('pointerdown', handler)
  }, [open])

  // Close on Escape
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open])

  // Close when a button inside the popover is clicked
  const handlePopoverClick = useCallback((e: React.MouseEvent) => {
    const target = e.target as HTMLElement
    if (target.closest('button')) {
      // Defer so the button's own onClick fires first
      requestAnimationFrame(() => setOpen(false))
    }
  }, [])

  const wrapperClass = [
    'action-menu',
    pushRight && 'push-right',
    className,
  ].filter(Boolean).join(' ')

  const triggerClass = [
    'action-menu-trigger',
    isActive && 'active',
    open && 'open',
  ].filter(Boolean).join(' ')

  return (
    <div className={wrapperClass} ref={menuRef}>
      <button
        className={triggerClass}
        onClick={() => setOpen(!open)}
        aria-label={triggerAriaLabel}
        aria-expanded={open}
      >
        {trigger}
        {badge != null && badge > 0 && (
          <span className="action-menu-badge">{badge}</span>
        )}
      </button>
      {open && (
        <div
          className={`action-menu-popover ${align === 'right' ? 'align-right' : 'align-left'}`}
          onClick={handlePopoverClick}
        >
          {children}
        </div>
      )}
    </div>
  )
}

/** A single item inside an ActionMenu popover. */
export function ActionMenuItem({
  onClick, active, children, className,
}: {
  onClick?: () => void
  active?: boolean
  children: ReactNode
  className?: string
}) {
  const cls = [
    'action-menu-item',
    active && 'item-active',
    className,
  ].filter(Boolean).join(' ')

  return (
    <button className={cls} onClick={onClick}>
      {children}
    </button>
  )
}
