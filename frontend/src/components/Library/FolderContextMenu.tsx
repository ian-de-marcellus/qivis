import { useCallback, useRef, useState } from 'react'
import { useClickOutside } from '../../hooks/useClickOutside.ts'
import { useEscapeKey } from '../../hooks/useEscapeKey.ts'

interface Props {
  folderPath: string
  treeCount: number
  isGhost: boolean
  x: number
  y: number
  onClose: () => void
  onNewSubfolder: (parentPath: string) => void
  onRename: (oldPath: string, newPath: string) => void
  onDelete: (path: string) => void
}

type View = 'menu' | 'rename' | 'confirm-delete'

export function FolderContextMenu({
  folderPath, treeCount, isGhost, x, y,
  onClose, onNewSubfolder, onRename, onDelete,
}: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const [view, setView] = useState<View>('menu')
  const [renameValue, setRenameValue] = useState(folderPath)

  const close = useCallback(() => onClose(), [onClose])
  useClickOutside(ref, true, close)
  useEscapeKey(true, close)

  const style: React.CSSProperties = {
    position: 'fixed',
    left: Math.min(x, window.innerWidth - 220),
    top: Math.min(y, window.innerHeight - 200),
    zIndex: 1001,
  }

  const handleRename = () => {
    const trimmed = renameValue.trim()
    if (trimmed && trimmed !== folderPath) {
      onRename(folderPath, trimmed)
    }
    onClose()
  }

  const handleDelete = () => {
    onDelete(folderPath)
    onClose()
  }

  return (
    <div ref={ref} className="rhizome-context-menu" style={style}>
      {view === 'menu' && (
        <>
          <button
            className="rhizome-context-item"
            onClick={() => { onNewSubfolder(folderPath); onClose() }}
          >
            New Subfolder
          </button>
          <button
            className="rhizome-context-item"
            onClick={() => setView('rename')}
          >
            Rename
          </button>
          <div className="rhizome-context-divider" />
          <button
            className="rhizome-context-item rhizome-context-item--danger"
            onClick={() => {
              if (treeCount === 0 || isGhost) {
                handleDelete()
              } else {
                setView('confirm-delete')
              }
            }}
          >
            Delete
          </button>
        </>
      )}

      {view === 'rename' && (
        <div className="rhizome-context-picker">
          <div className="rhizome-context-picker-header">
            <button className="rhizome-context-back" onClick={() => setView('menu')}>
              &larr;
            </button>
            <span>Rename Folder</span>
          </div>
          <input
            type="text"
            className="rhizome-context-input"
            value={renameValue}
            onChange={e => setRenameValue(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') handleRename()
              if (e.key === 'Escape') onClose()
            }}
            autoFocus
          />
        </div>
      )}

      {view === 'confirm-delete' && (
        <div className="rhizome-context-picker">
          <div className="rhizome-context-picker-header">
            <button className="rhizome-context-back" onClick={() => setView('menu')}>
              &larr;
            </button>
            <span>Delete Folder</span>
          </div>
          <p style={{
            fontFamily: 'var(--font-ui)',
            fontSize: 'var(--text-xs)',
            color: 'var(--text-secondary)',
            margin: 0,
            lineHeight: 1.4,
          }}>
            Remove folder from {treeCount} tree{treeCount !== 1 ? 's' : ''}?
            Trees will become unsorted.
          </p>
          <button
            className="rhizome-context-item rhizome-context-item--danger"
            onClick={handleDelete}
          >
            Remove from {treeCount} tree{treeCount !== 1 ? 's' : ''}
          </button>
        </div>
      )}
    </div>
  )
}
