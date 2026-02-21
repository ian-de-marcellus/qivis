import { useMemo } from 'react'
import type { TreeSummary } from '../../api/types.ts'
import { findFolderNode, collectTreeIds, type FolderNode } from '../../utils/folderTrie.ts'
import { DraggableTreeCard } from './DraggableTreeCard.tsx'

interface Props {
  trees: TreeSummary[]
  selectedFolder: string | null
  folderTrie: FolderNode[]
  selectedIds: Set<string>
  onSelect: (id: string, e: React.MouseEvent) => void
  onClick: (treeId: string) => void
  onRemoveFolder: (treeId: string, folder: string) => void
  onArchive: (treeId: string) => void
  onUnarchive: (treeId: string) => void
  onContextMenu: (e: React.MouseEvent, treeId: string) => void
}

export function TreeCardGrid({
  trees, selectedFolder, folderTrie, selectedIds,
  onSelect, onClick, onRemoveFolder, onArchive, onUnarchive, onContextMenu,
}: Props) {
  const showCheckboxes = selectedIds.size > 0

  // Filter trees based on selected folder
  const filtered = useMemo(() => {
    const sorted = [...trees].sort(
      (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
    )

    if (selectedFolder === null) return sorted
    if (selectedFolder === '__unsorted__') return sorted.filter(t => t.folders.length === 0)

    // Show trees in this folder or any descendant
    const folderNode = findFolderNode(folderTrie, selectedFolder)
    if (!folderNode) return sorted.filter(t => t.folders.includes(selectedFolder))

    const idsInFolder = new Set(collectTreeIds(folderNode))
    return sorted.filter(t => idsInFolder.has(t.tree_id))
  }, [trees, selectedFolder, folderTrie])

  const label = selectedFolder === null
    ? 'All Trees'
    : selectedFolder === '__unsorted__'
      ? 'Unsorted'
      : selectedFolder.split('/').pop()

  return (
    <div className="library-content-panel">
      <div className="library-content-header">
        <span className="library-content-title">{label}</span>
        <span className="library-content-count">{filtered.length} tree{filtered.length !== 1 ? 's' : ''}</span>
      </div>
      <div className="library-grid">
        {filtered.map(tree => (
          <DraggableTreeCard
            key={tree.tree_id}
            tree={tree}
            isSelected={selectedIds.has(tree.tree_id)}
            showCheckboxes={showCheckboxes}
            onSelect={onSelect}
            onClick={onClick}
            onRemoveFolder={onRemoveFolder}
            onArchive={onArchive}
            onUnarchive={onUnarchive}
            onContextMenu={onContextMenu}
          />
        ))}
        {filtered.length === 0 && (
          <p className="library-empty">
            {selectedFolder === '__unsorted__'
              ? 'All trees are organized into folders.'
              : selectedFolder
                ? 'No trees in this folder yet. Drag trees here to organize them.'
                : 'No trees yet. Create one to start.'}
          </p>
        )}
      </div>
    </div>
  )
}
