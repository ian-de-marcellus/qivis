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
    <div ref={ref} className="tree-context-menu" style={style}>
      {view === 'menu' && (
        <>
          <button
            className="tree-context-item"
            onClick={() => { onNewSubfolder(folderPath); onClose() }}
          >
            New Subfolder
          </button>
          <button
            className="tree-context-item"
            onClick={() => setView('rename')}
          >
            Rename
          </button>
          <div className="tree-context-divider" />
          <button
            className="tree-context-item tree-context-item--danger"
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
        <div className="tree-context-picker">
          <div className="tree-context-picker-header">
            <button className="tree-context-back" onClick={() => setView('menu')}>
              &larr;
            </button>
            <span>Rename Folder</span>
          </div>
          <input
            type="text"
            className="tree-context-input"
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
        <div className="tree-context-picker">
          <div className="tree-context-picker-header">
            <button className="tree-context-back" onClick={() => setView('menu')}>
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
            className="tree-context-item tree-context-item--danger"
            onClick={handleDelete}
          >
            Remove from {treeCount} tree{treeCount !== 1 ? 's' : ''}
          </button>
        </div>
      )}
    </div>
  )
}
