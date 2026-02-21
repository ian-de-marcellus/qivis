import { useDraggable } from '@dnd-kit/core'
import type { TreeSummary } from '../../api/types.ts'
import { tagColor } from '../../utils/tagColor.ts'

interface Props {
  tree: TreeSummary
  isSelected: boolean
  showCheckboxes: boolean
  onSelect: (id: string, e: React.MouseEvent) => void
  onClick: (treeId: string) => void
  onRemoveFolder: (treeId: string, folder: string) => void
  onArchive: (treeId: string) => void
  onUnarchive: (treeId: string) => void
  onContextMenu: (e: React.MouseEvent, treeId: string) => void
}

export function DraggableTreeCard({
  tree, isSelected, showCheckboxes, onSelect, onClick, onRemoveFolder, onArchive, onUnarchive, onContextMenu,
}: Props) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: `tree:${tree.tree_id}`,
  })

  const style = transform ? {
    transform: `translate3d(${transform.x}px, ${transform.y}px, 0)`,
  } : undefined

  const isArchived = tree.archived === 1

  const classes = [
    'tree-card',
    isSelected ? 'tree-card--selected' : '',
    isDragging ? 'tree-card--dragging' : '',
    isArchived ? 'tree-card--archived' : '',
    showCheckboxes ? 'tree-card--show-checkboxes' : '',
  ].filter(Boolean).join(' ')

  return (
    <div
      ref={setNodeRef}
      className={classes}
      style={style}
      {...listeners}
      {...attributes}
      onContextMenu={(e) => { e.preventDefault(); onContextMenu(e, tree.tree_id) }}
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey) {
          onSelect(tree.tree_id, e)
        } else {
          onClick(tree.tree_id)
        }
      }}
    >
      {/* Checkbox */}
      <span
        className={`tree-card-checkbox ${isSelected ? 'checked' : ''}`}
        onClick={(e) => {
          e.stopPropagation()
          onSelect(tree.tree_id, e)
        }}
      >
        {isSelected ? '\u2713' : ''}
      </span>

      {/* Title */}
      <span className="tree-card-title">{tree.title || 'Untitled'}</span>

      {/* Meta row: date + tags */}
      <span className="tree-card-meta">
        <span className="tree-card-date">
          {new Date(tree.updated_at).toLocaleDateString()}
        </span>
        {isArchived && <span className="tree-card-archived-label">archived</span>}
        {tree.tags.length > 0 && (
          <span className="tree-card-tags">
            {tree.tags.map(t => (
              <span
                key={t}
                className="tree-card-tag-dot"
                style={{ background: tagColor(t) }}
                title={t}
              />
            ))}
          </span>
        )}
      </span>

      {/* Folder chips + archive action */}
      <span className="tree-card-bottom">
        {tree.folders.length > 0 && (
          <span className="tree-card-folders">
            {tree.folders.map(f => (
              <span key={f} className="tree-card-folder-chip">
                {f.split('/').pop()}
                <button
                  onClick={(e) => { e.stopPropagation(); onRemoveFolder(tree.tree_id, f) }}
                  title={`Remove from ${f}`}
                >
                  &times;
                </button>
              </span>
            ))}
          </span>
        )}
        {isArchived ? (
          <button
            className="tree-card-archive-btn"
            onClick={(e) => { e.stopPropagation(); onUnarchive(tree.tree_id) }}
            title="Unarchive"
          >
            Unarchive
          </button>
        ) : (
          <button
            className="tree-card-archive-btn"
            onClick={(e) => { e.stopPropagation(); onArchive(tree.tree_id) }}
            title="Archive"
          >
            Archive
          </button>
        )}
      </span>
    </div>
  )
}
