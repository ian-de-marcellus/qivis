import { useCallback, useRef, useState } from 'react'
import * as api from '../../api/client.ts'
import { useClickOutside } from '../../hooks/useClickOutside.ts'
import { useEscapeKey } from '../../hooks/useEscapeKey.ts'
import { useTreeStore } from '../../store/treeStore.ts'
import type { TreeSummary } from '../../api/types.ts'
import { tagColor } from '../../utils/tagColor.ts'
import './TreeContextMenu.css'

interface Props {
  tree: TreeSummary
  x: number
  y: number
  allTrees: TreeSummary[]
  onClose: () => void
  onRename: () => void
}

type View = 'menu' | 'folder-picker' | 'tag-picker'

export function TreeContextMenu({ tree, x, y, allTrees, onClose, onRename }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const [view, setView] = useState<View>('menu')
  const [folderInput, setFolderInput] = useState('')
  const [tagInput, setTagInput] = useState('')

  const updateTree = useTreeStore(s => s.updateTree)
  const archiveTree = useTreeStore(s => s.archiveTree)
  const unarchiveTree = useTreeStore(s => s.unarchiveTree)

  const close = useCallback(() => onClose(), [onClose])

  useClickOutside(ref, true, close)
  useEscapeKey(true, close)

  // Derive existing folders and tags from all trees
  const existingFolders = [...new Set(allTrees.flatMap(t => t.folders))].sort()
  const existingTags = [...new Set(allTrees.flatMap(t => t.tags))].sort()

  // Current tree's metadata (for display)
  const currentFolders = tree.folders ?? []
  const currentTags = tree.tags ?? []

  // Read-merge-write: fetch full metadata, merge change, then patch
  const mergeMetadata = async (patch: Record<string, unknown>) => {
    const full = await api.getTree(tree.tree_id)
    const merged = { ...full.metadata, ...patch }
    await updateTree(tree.tree_id, { metadata: merged })
  }

  const addFolder = async (folder: string) => {
    const trimmed = folder.trim()
    if (!trimmed || currentFolders.includes(trimmed)) return
    await mergeMetadata({ folders: [...currentFolders, trimmed] })
    onClose()
  }

  const removeFolder = async (folder: string) => {
    await mergeMetadata({ folders: currentFolders.filter(f => f !== folder) })
    onClose()
  }

  const addTag = async (tag: string) => {
    const trimmed = tag.trim().toLowerCase()
    if (!trimmed || currentTags.includes(trimmed)) return
    await mergeMetadata({ tags: [...currentTags, trimmed] })
    onClose()
  }

  const removeTag = async (tag: string) => {
    await mergeMetadata({ tags: currentTags.filter(t => t !== tag) })
    onClose()
  }

  // Clamp position to viewport
  const style: React.CSSProperties = {
    position: 'fixed',
    left: Math.min(x, window.innerWidth - 220),
    top: Math.min(y, window.innerHeight - 300),
    zIndex: 1000,
  }

  const isArchived = tree.archived === 1

  // Filter existing folders/tags to exclude those already on this tree
  const suggestedFolders = existingFolders.filter(f => !currentFolders.includes(f))
  const suggestedTags = existingTags.filter(t => !currentTags.includes(t))

  return (
    <div ref={ref} className="tree-context-menu" style={style}>
      {view === 'menu' && (
        <>
          <button
            className="tree-context-item"
            onClick={() => { onRename(); onClose() }}
          >
            Rename
          </button>
          <button
            className="tree-context-item"
            onClick={() => setView('folder-picker')}
          >
            Folders...
          </button>
          <button
            className="tree-context-item"
            onClick={() => setView('tag-picker')}
          >
            Tags...
          </button>
          <div className="tree-context-divider" />
          {isArchived ? (
            <button
              className="tree-context-item"
              onClick={() => { unarchiveTree(tree.tree_id); onClose() }}
            >
              Unarchive
            </button>
          ) : (
            <button
              className="tree-context-item tree-context-item--danger"
              onClick={() => { archiveTree(tree.tree_id); onClose() }}
            >
              Archive
            </button>
          )}
        </>
      )}

      {view === 'folder-picker' && (
        <div className="tree-context-picker">
          <div className="tree-context-picker-header">
            <button className="tree-context-back" onClick={() => setView('menu')}>
              &larr;
            </button>
            <span>Folders</span>
          </div>

          {currentFolders.length > 0 && (
            <div className="tree-context-current">
              {currentFolders.map(f => (
                <span key={f} className="tree-context-folder-chip">
                  {f}
                  <button onClick={() => removeFolder(f)}>&times;</button>
                </span>
              ))}
            </div>
          )}

          <input
            type="text"
            className="tree-context-input"
            placeholder="New folder path..."
            value={folderInput}
            onChange={e => setFolderInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') {
                addFolder(folderInput)
              }
            }}
            autoFocus
          />

          {suggestedFolders.length > 0 && (
            <div className="tree-context-suggestions">
              {suggestedFolders.map(f => (
                <button
                  key={f}
                  className="tree-context-suggestion"
                  onClick={() => addFolder(f)}
                >
                  {f}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {view === 'tag-picker' && (
        <div className="tree-context-picker">
          <div className="tree-context-picker-header">
            <button className="tree-context-back" onClick={() => setView('menu')}>
              &larr;
            </button>
            <span>Tags</span>
          </div>

          {currentTags.length > 0 && (
            <div className="tree-context-current">
              {currentTags.map(t => (
                <span
                  key={t}
                  className="tree-context-tag-chip"
                  style={{ borderColor: tagColor(t) }}
                >
                  <span className="tree-context-tag-dot" style={{ background: tagColor(t) }} />
                  {t}
                  <button onClick={() => removeTag(t)}>&times;</button>
                </span>
              ))}
            </div>
          )}

          <input
            type="text"
            className="tree-context-input"
            placeholder="New tag..."
            value={tagInput}
            onChange={e => setTagInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') {
                addTag(tagInput)
              }
            }}
            autoFocus
          />

          {suggestedTags.length > 0 && (
            <div className="tree-context-suggestions">
              {suggestedTags.map(t => (
                <button
                  key={t}
                  className="tree-context-suggestion"
                  onClick={() => addTag(t)}
                >
                  <span className="tree-context-tag-dot" style={{ background: tagColor(t) }} />
                  {t}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
