import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  KeyboardSensor,
  useSensor,
  useSensors,
  closestCenter,
  type DragStartEvent,
  type DragEndEvent,
} from '@dnd-kit/core'
import * as api from '../../api/client.ts'
import type { TreeSummary } from '../../api/types.ts'
import { useTreeStore, useTreeData } from '../../store/treeStore.ts'
import { useModalBehavior } from '../../hooks/useModalBehavior.ts'
import { buildFolderTrie } from '../../utils/folderTrie.ts'
import { FolderTreePanel } from './FolderTreePanel.tsx'
import { TreeCardGrid } from './TreeCardGrid.tsx'
import { LibraryDragOverlay } from './LibraryDragOverlay.tsx'
import { TreeContextMenu } from './TreeContextMenu.tsx'
import { FolderContextMenu } from './FolderContextMenu.tsx'
import './LibraryView.css'

const GHOST_FOLDERS_KEY = 'qivis-library-folders'

function getStoredGhostFolders(): string[] {
  try {
    const stored = localStorage.getItem(GHOST_FOLDERS_KEY)
    return stored ? JSON.parse(stored) : []
  } catch {
    return []
  }
}

interface Props {
  onDismiss: () => void
}

export function LibraryView({ onDismiss }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const { handleBackdropClick } = useModalBehavior(ref, onDismiss)

  const { trees } = useTreeData()
  const updateTree = useTreeStore(s => s.updateTree)
  const selectTree = useTreeStore(s => s.selectTree)
  const setLibraryOpen = useTreeStore(s => s.setLibraryOpen)
  const archiveTree = useTreeStore(s => s.archiveTree)
  const unarchiveTree = useTreeStore(s => s.unarchiveTree)
  const fetchTrees = useTreeStore(s => s.fetchTrees)

  const [selectedFolder, setSelectedFolder] = useState<string | null>(null)
  const [ghostFolders, setGhostFolders] = useState<string[]>(getStoredGhostFolders)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const draggedTreeIdsRef = useRef<string[]>([])
  const [, setDragVersion] = useState(0) // trigger re-render for overlay
  const [contextMenu, setContextMenu] = useState<{ treeId: string; x: number; y: number } | null>(null)
  const [folderContextMenu, setFolderContextMenu] = useState<{ path: string; x: number; y: number } | null>(null)
  const [folderInputPrefill, setFolderInputPrefill] = useState<string | null>(null)
  const [showArchived, setShowArchived] = useState(false)
  const lastClickedId = useRef<string | null>(null)

  // Refetch when showArchived changes
  useEffect(() => {
    fetchTrees(showArchived)
  }, [showArchived, fetchTrees])

  // Archive/unarchive handlers
  const handleArchive = useCallback(async (treeId: string) => {
    await archiveTree(treeId)
    // Refetch to update the list
    await fetchTrees(showArchived)
  }, [archiveTree, fetchTrees, showArchived])

  const handleUnarchive = useCallback(async (treeId: string) => {
    await unarchiveTree(treeId)
    await fetchTrees(showArchived)
  }, [unarchiveTree, fetchTrees, showArchived])

  // Sorted trees for ordered operations
  const sortedTrees = useMemo(() =>
    [...trees].sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()),
  [trees])

  const treeMap = useMemo(() => new Map(trees.map(t => [t.tree_id, t])), [trees])

  const folderTrie = useMemo(() =>
    buildFolderTrie(sortedTrees, ghostFolders),
  [sortedTrees, ghostFolders])

  // DnD sensors
  const pointerSensor = useSensor(PointerSensor, {
    activationConstraint: { distance: 8 },
  })
  const keyboardSensor = useSensor(KeyboardSensor)
  const sensors = useSensors(pointerSensor, keyboardSensor)

  // Read-merge-write metadata pattern
  const mergeMetadata = useCallback(async (treeId: string, patch: Record<string, unknown>) => {
    const full = await api.getTree(treeId)
    const merged = { ...full.metadata, ...patch }
    await updateTree(treeId, { metadata: merged })
  }, [updateTree])

  // Multi-select handlers
  const handleSelect = useCallback((id: string, e: React.MouseEvent) => {
    if (e.metaKey || e.ctrlKey) {
      // Toggle
      setSelectedIds(prev => {
        const next = new Set(prev)
        if (next.has(id)) next.delete(id)
        else next.add(id)
        return next
      })
    } else if (e.shiftKey && lastClickedId.current) {
      // Range select
      const ids = sortedTrees.map(t => t.tree_id)
      const start = ids.indexOf(lastClickedId.current)
      const end = ids.indexOf(id)
      if (start !== -1 && end !== -1) {
        const [lo, hi] = start < end ? [start, end] : [end, start]
        const range = ids.slice(lo, hi + 1)
        setSelectedIds(prev => {
          const next = new Set(prev)
          for (const rid of range) next.add(rid)
          return next
        })
      }
    } else {
      // Single select (toggle)
      setSelectedIds(prev => {
        const next = new Set<string>()
        if (!prev.has(id)) next.add(id)
        return next
      })
    }
    lastClickedId.current = id
  }, [sortedTrees])

  const clearSelection = useCallback(() => {
    setSelectedIds(new Set())
  }, [])

  // Bulk archive for selected trees
  const handleArchiveSelected = useCallback(async () => {
    const ids = [...selectedIds]
    for (const id of ids) {
      await archiveTree(id)
    }
    clearSelection()
    await fetchTrees(showArchived)
  }, [selectedIds, archiveTree, clearSelection, fetchTrees, showArchived])

  // Card click (navigate to tree)
  const handleCardClick = useCallback((treeId: string) => {
    selectTree(treeId)
    setLibraryOpen(false)
  }, [selectTree, setLibraryOpen])

  // Remove a folder from a tree
  const handleRemoveFolder = useCallback(async (treeId: string, folder: string) => {
    const tree = treeMap.get(treeId)
    if (!tree) return
    await mergeMetadata(treeId, { folders: tree.folders.filter(f => f !== folder) })
  }, [treeMap, mergeMetadata])

  // Create ghost folder
  const handleCreateFolder = useCallback((path: string) => {
    setGhostFolders(prev => {
      if (prev.includes(path)) return prev
      const next = [...prev, path]
      localStorage.setItem(GHOST_FOLDERS_KEY, JSON.stringify(next))
      return next
    })
  }, [])

  // Rename folder: update all trees that reference the old path
  const handleRenameFolder = useCallback(async (oldPath: string, newPath: string) => {
    const affected = trees.filter(t =>
      t.folders.some(f => f === oldPath || f.startsWith(oldPath + '/'))
    )
    await Promise.all(affected.map(async (tree) => {
      const newFolders = tree.folders.map(f => {
        if (f === oldPath) return newPath
        if (f.startsWith(oldPath + '/')) return newPath + f.slice(oldPath.length)
        return f
      })
      await mergeMetadata(tree.tree_id, { folders: newFolders })
    }))
    // Update ghost folders too
    setGhostFolders(prev => {
      const next = prev.map(f => {
        if (f === oldPath) return newPath
        if (f.startsWith(oldPath + '/')) return newPath + f.slice(oldPath.length)
        return f
      })
      localStorage.setItem(GHOST_FOLDERS_KEY, JSON.stringify(next))
      return next
    })
  }, [trees, mergeMetadata])

  // Delete folder: remove from all trees and ghost folders
  const handleDeleteFolder = useCallback(async (path: string) => {
    const affected = trees.filter(t =>
      t.folders.some(f => f === path || f.startsWith(path + '/'))
    )
    if (affected.length > 0) {
      await Promise.all(affected.map(async (tree) => {
        const newFolders = tree.folders.filter(f => f !== path && !f.startsWith(path + '/'))
        await mergeMetadata(tree.tree_id, { folders: newFolders })
      }))
    }
    // Remove from ghost folders
    setGhostFolders(prev => {
      const next = prev.filter(f => f !== path && !f.startsWith(path + '/'))
      localStorage.setItem(GHOST_FOLDERS_KEY, JSON.stringify(next))
      return next
    })
    // If we were viewing the deleted folder, go back to All
    if (selectedFolder === path || selectedFolder?.startsWith(path + '/')) {
      setSelectedFolder(null)
    }
  }, [trees, mergeMetadata, selectedFolder])

  // Folder context menu
  const handleFolderContextMenu = useCallback((e: React.MouseEvent, folderPath: string) => {
    setFolderContextMenu({ path: folderPath, x: e.clientX, y: e.clientY })
  }, [])

  // Context menu
  const handleCardContextMenu = useCallback((e: React.MouseEvent, treeId: string) => {
    e.preventDefault()
    setContextMenu({ treeId, x: e.clientX, y: e.clientY })
  }, [])

  // DnD handlers
  const handleDragStart = useCallback((event: DragStartEvent) => {
    const treeId = String(event.active.id).replace('tree:', '')
    if (selectedIds.has(treeId)) {
      draggedTreeIdsRef.current = [...selectedIds]
    } else {
      draggedTreeIdsRef.current = [treeId]
      setSelectedIds(new Set())
    }
    setDragVersion(v => v + 1)
  }, [selectedIds])

  const handleDragEnd = useCallback(async (event: DragEndEvent) => {
    const { over } = event
    const treeIds = [...draggedTreeIdsRef.current]
    draggedTreeIdsRef.current = []
    setDragVersion(v => v + 1)

    if (!over || treeIds.length === 0) return
    const dropTarget = String(over.id).replace('folder:', '')
    if (!dropTarget) return

    if (dropTarget === '__unsorted__') {
      await Promise.all(treeIds.map(id => mergeMetadata(id, { folders: [] })))
    } else {
      await Promise.all(treeIds.map(async (id) => {
        const tree = treeMap.get(id)
        if (tree && !tree.folders.includes(dropTarget)) {
          await mergeMetadata(id, { folders: [...tree.folders, dropTarget] })
        }
      }))
    }

    clearSelection()
  }, [treeMap, mergeMetadata, clearSelection])

  // Trees for the drag overlay
  const draggedTrees = draggedTreeIdsRef.current
    .map(id => treeMap.get(id))
    .filter((t): t is TreeSummary => t != null)

  return (
    <div className="library-backdrop" onClick={handleBackdropClick}>
      <div ref={ref} className="library-view" tabIndex={-1}>
        {/* Header */}
        <div className="library-header">
          <div className="library-header-left">
            <span className="library-title">Library</span>
            <span className="library-subtitle">{trees.length} tree{trees.length !== 1 ? 's' : ''}</span>
          </div>
          <div className="library-header-right">
            {selectedIds.size > 0 && (
              <span className="library-selection-info">
                {selectedIds.size} selected
                <button className="library-action-btn" onClick={handleArchiveSelected}>Archive</button>
                <button className="library-clear-btn" onClick={clearSelection}>Clear</button>
              </span>
            )}
            <label className="library-archive-toggle">
              <input
                type="checkbox"
                checked={showArchived}
                onChange={e => setShowArchived(e.target.checked)}
              />
              Show archived
            </label>
            <button className="library-close" onClick={onDismiss}>Close</button>
          </div>
        </div>

        {/* Body */}
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragStart={handleDragStart}
          onDragEnd={handleDragEnd}
        >
          <div className="library-body">
            <FolderTreePanel
              trees={sortedTrees}
              ghostFolders={ghostFolders}
              selectedFolder={selectedFolder}
              prefillInput={folderInputPrefill}
              onSelectFolder={setSelectedFolder}
              onCreateFolder={handleCreateFolder}
              onClearPrefill={() => setFolderInputPrefill(null)}
              onContextMenu={handleFolderContextMenu}
            />
            <TreeCardGrid
              trees={sortedTrees}
              selectedFolder={selectedFolder}
              folderTrie={folderTrie}
              selectedIds={selectedIds}
              onSelect={handleSelect}
              onClick={handleCardClick}
              onRemoveFolder={handleRemoveFolder}
              onArchive={handleArchive}
              onUnarchive={handleUnarchive}
              onContextMenu={handleCardContextMenu}
            />
          </div>

          <DragOverlay dropAnimation={null}>
            {draggedTrees.length > 0 && (
              <LibraryDragOverlay trees={draggedTrees} />
            )}
          </DragOverlay>
        </DndContext>

        {/* Tree context menu */}
        {contextMenu && (
          <TreeContextMenu
            tree={trees.find(t => t.tree_id === contextMenu.treeId)!}
            x={contextMenu.x}
            y={contextMenu.y}
            allTrees={trees}
            onClose={() => setContextMenu(null)}
            onRename={() => setContextMenu(null)}
          />
        )}

        {/* Folder context menu */}
        {folderContextMenu && (() => {
          const path = folderContextMenu.path
          const count = trees.filter(t =>
            t.folders.some(f => f === path || f.startsWith(path + '/'))
          ).length
          const isGhost = !trees.some(t => t.folders.includes(path)) && ghostFolders.includes(path)
          return (
            <FolderContextMenu
              folderPath={path}
              treeCount={count}
              isGhost={isGhost}
              x={folderContextMenu.x}
              y={folderContextMenu.y}
              onClose={() => setFolderContextMenu(null)}
              onNewSubfolder={(parentPath) => setFolderInputPrefill(parentPath + '/')}
              onRename={handleRenameFolder}
              onDelete={handleDeleteFolder}
            />
          )
        })()}
      </div>
    </div>
  )
}
