import { useCallback, useEffect } from 'react'

const FOCUSABLE = 'a[href], button:not(:disabled), textarea:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex="-1"])'

/**
 * Shared modal behavior: Escape to dismiss, backdrop click to dismiss,
 * and focus trap within the modal container.
 */
export function useModalBehavior(
  ref: React.RefObject<HTMLElement | null>,
  onDismiss: () => void,
) {
  // Escape key handler
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onDismiss()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [onDismiss])

  // Focus trap: on mount, focus first focusable element.
  // On tab/shift+tab, cycle within the modal.
  useEffect(() => {
    const el = ref.current
    if (!el) return

    // Focus the first focusable element, or the container itself
    const first = el.querySelector<HTMLElement>(FOCUSABLE)
    if (first) {
      first.focus()
    } else {
      el.focus()
    }

    const handleTab = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return
      const focusable = Array.from(el.querySelectorAll<HTMLElement>(FOCUSABLE))
      if (focusable.length === 0) return

      const firstEl = focusable[0]
      const lastEl = focusable[focusable.length - 1]

      if (e.shiftKey) {
        if (document.activeElement === firstEl) {
          e.preventDefault()
          lastEl.focus()
        }
      } else {
        if (document.activeElement === lastEl) {
          e.preventDefault()
          firstEl.focus()
        }
      }
    }

    el.addEventListener('keydown', handleTab)
    return () => el.removeEventListener('keydown', handleTab)
  }, [ref])

  // Backdrop click: dismiss when clicking the backdrop (not its children)
  const handleBackdropClick = useCallback((e: React.MouseEvent) => {
    if (e.target === e.currentTarget) onDismiss()
  }, [onDismiss])

  return { handleBackdropClick }
}
