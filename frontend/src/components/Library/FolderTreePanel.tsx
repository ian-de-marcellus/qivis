import { useCallback, useEffect, useRef, useState } from 'react'
import { useDroppable } from '@dnd-kit/core'
import type { TreeSummary } from '../../api/types.ts'
import { type FolderNode, buildFolderTrie, countTreesInFolder } from '../../utils/folderTrie.ts'

interface Props {
  trees: TreeSummary[]
  ghostFolders: string[]
  selectedFolder: string | null
  prefillInput: string | null
  onSelectFolder: (folder: string | null) => void
  onCreateFolder: (path: string) => void
  onClearPrefill: () => void
  onContextMenu?: (e: React.MouseEvent, folderPath: string) => void
}

const COLLAPSED_KEY = 'qivis-library-collapsed'

function getStoredCollapsed(): Set<string> {
  try {
    const stored = localStorage.getItem(COLLAPSED_KEY)
    return stored ? new Set(JSON.parse(stored)) : new Set()
  } catch {
    return new Set()
  }
}

export function FolderTreePanel({
  trees, ghostFolders, selectedFolder, prefillInput, onSelectFolder, onCreateFolder, onClearPrefill, onContextMenu,
}: Props) {
  const [collapsed, setCollapsed] = useState<Set<string>>(getStoredCollapsed)
  const [folderInput, setFolderInput] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  // Handle prefill from parent (e.g., "New Subfolder" action)
  useEffect(() => {
    if (prefillInput !== null) {
      setFolderInput(prefillInput)
      onClearPrefill()
      inputRef.current?.focus()
    }
  }, [prefillInput, onClearPrefill])

  const treeMap = new Map(trees.map(t => [t.tree_id, t]))
  const folderTrie = buildFolderTrie(trees, ghostFolders)
  const unsortedCount = trees.filter(t => t.folders.length === 0).length
  const totalCount = trees.length

  // Track which folders exist from actual tree data vs ghost-only
  const realFolders = new Set(trees.flatMap(t => t.folders))

  const toggleCollapse = useCallback((path: string) => {
    setCollapsed(prev => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...next]))
      return next
    })
  }, [])

  const handleCreateFolder = () => {
    const trimmed = folderInput.trim()
    if (trimmed) {
      onCreateFolder(trimmed)
      setFolderInput('')
    }
  }

  const renderFolderNode = (node: FolderNode, depth: number) => {
    const isCollapsed = collapsed.has(node.path)
    const count = countTreesInFolder(node, treeMap)
    const hasChildren = node.children.length > 0
    const isGhost = !realFolders.has(node.path) && count === 0

    return (
      <div key={node.path}>
        <DroppableFolderRow
          path={node.path}
          name={node.name}
          count={count}
          depth={depth}
          isActive={selectedFolder === node.path}
          isGhost={isGhost}
          hasChildren={hasChildren}
          isCollapsed={isCollapsed}
          onSelect={() => onSelectFolder(node.path)}
          onToggle={() => toggleCollapse(node.path)}
          onContextMenu={onContextMenu}
        />
        {hasChildren && !isCollapsed && (
          node.children.map(child => renderFolderNode(child, depth + 1))
        )}
      </div>
    )
  }

  return (
    <div className="library-folder-panel">
      <div className="library-folder-list">
        {/* All Trees */}
        <button
          className={`library-folder-row library-folder-row--special ${selectedFolder === null ? 'active' : ''}`}
          onClick={() => onSelectFolder(null)}
        >
          <span className="library-folder-chevron spacer">&#9654;</span>
          <span className="library-folder-name">All Trees</span>
          <span className="library-folder-count">{totalCount}</span>
        </button>

        {/* Unsorted */}
        <DroppableFolderRow
          path="__unsorted__"
          name="Unsorted"
          count={unsortedCount}
          depth={0}
          isActive={selectedFolder === '__unsorted__'}
          isGhost={false}
          hasChildren={false}
          isCollapsed={false}
          isSpecial
          onSelect={() => onSelectFolder('__unsorted__')}
          onToggle={() => {}}
        />

        {/* Folder trie */}
        {folderTrie.map(node => renderFolderNode(node, 0))}
      </div>

      {/* New folder input */}
      <div className="library-new-folder">
        <input
          ref={inputRef}
          className="library-new-folder-input"
          type="text"
          placeholder="+ New folder path..."
          value={folderInput}
          onChange={e => setFolderInput(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter') handleCreateFolder()
            if (e.key === 'Escape') setFolderInput('')
          }}
        />
      </div>
    </div>
  )
}

/* ---- Droppable folder row ---- */

interface DroppableFolderRowProps {
  path: string
  name: string
  count: number
  depth: number
  isActive: boolean
  isGhost: boolean
  hasChildren: boolean
  isCollapsed: boolean
  isSpecial?: boolean
  onSelect: () => void
  onToggle: () => void
  onContextMenu?: (e: React.MouseEvent, folderPath: string) => void
}

function DroppableFolderRow({
  path, name, count, depth, isActive, isGhost, hasChildren, isCollapsed,
  isSpecial, onSelect, onToggle, onContextMenu,
}: DroppableFolderRowProps) {
  const { setNodeRef, isOver } = useDroppable({ id: `folder:${path}` })

  const classes = [
    'library-folder-row',
    isActive ? 'active' : '',
    isOver ? 'drop-over' : '',
    isSpecial ? 'library-folder-row--special' : '',
    isGhost ? 'library-folder-row--ghost' : '',
  ].filter(Boolean).join(' ')

  return (
    <button
      ref={setNodeRef}
      className={classes}
      style={{ paddingLeft: `calc(var(--space-md) + ${depth * 16}px)` }}
      onClick={onSelect}
      onContextMenu={onContextMenu ? (e) => { e.preventDefault(); onContextMenu(e, path) } : undefined}
    >
      {hasChildren ? (
        <span
          className={`library-folder-chevron ${isCollapsed ? '' : 'expanded'}`}
          onClick={(e) => { e.stopPropagation(); onToggle() }}
        >
          &#9654;
        </span>
      ) : (
        <span className="library-folder-chevron spacer">&#9654;</span>
      )}
      <span className="library-folder-name">{name}</span>
      <span className="library-folder-count">{count}</span>
    </button>
  )
}
