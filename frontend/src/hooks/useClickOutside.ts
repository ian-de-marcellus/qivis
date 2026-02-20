import { useEffect } from 'react'

/**
 * Calls `onClickOutside` when a pointerdown event lands outside the referenced element,
 * only while `active` is true.
 */
export function useClickOutside(
  ref: React.RefObject<HTMLElement | null>,
  active: boolean,
  onClickOutside: () => void,
) {
  useEffect(() => {
    if (!active) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClickOutside()
      }
    }
    document.addEventListener('pointerdown', handler)
    return () => document.removeEventListener('pointerdown', handler)
  }, [ref, active, onClickOutside])
}
