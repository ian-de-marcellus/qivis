import { useCallback, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useEscapeKey } from '../../hooks/useEscapeKey.ts'
import { useClickOutside } from '../../hooks/useClickOutside.ts'
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

  useClickOutside(menuRef, open, () => setOpen(false))
  useEscapeKey(open, () => setOpen(false))

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
          <span className="badge">{badge}</span>
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
