import type { ReactNode } from 'react'

interface FirstTurnActionProps {
  /** Whether the root generation panel is open (forkTarget.parentId === ''). */
  open: boolean
  onOpen: () => void
  /** Steer the first turn token by token */
  onSteer: () => void
  /** The ForkPanel to show once opened, configured by the enclosing view. */
  panel: ReactNode
}

/**
 * Empty-rhizome action: let the model speak first, with no prior turns.
 * Opens the regular ForkPanel in generate mode at the root ('' parent key).
 */
export function FirstTurnAction({ open, onOpen, onSteer, panel }: FirstTurnActionProps) {
  if (open) return <>{panel}</>
  return (
    <div className="first-turn-empty">
      <p className="first-turn-lede">Nothing here yet.</p>
      <p className="first-turn-hint">Write the first message below, or let the model begin.</p>
      <div className="first-turn-row">
        <button className="first-turn-btn" onClick={onOpen}>Generate first turn</button>
        <button className="first-turn-btn" onClick={onSteer}>Steer first turn</button>
      </div>
    </div>
  )
}
