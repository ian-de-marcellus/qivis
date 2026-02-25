import { useDraggable } from '@dnd-kit/core'
import type { RhizomeSummary } from '../../api/types.ts'
import { tagColor } from '../../utils/tagColor.ts'

interface Props {
  tree: RhizomeSummary
  isSelected: boolean
  showCheckboxes: boolean
  onSelect: (id: string, e: React.MouseEvent) => void
  onClick: (treeId: string) => void
  onRemoveFolder: (treeId: string, folder: string) => void
  onArchive: (treeId: string) => void
  onUnarchive: (treeId: string) => void
  onContextMenu: (e: React.MouseEvent, treeId: string) => void
}

export function DraggableRhizomeCard({
  tree, isSelected, showCheckboxes, onSelect, onClick, onRemoveFolder, onArchive, onUnarchive, onContextMenu,
}: Props) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: `tree:${tree.rhizome_id}`,
  })

  const style = transform ? {
    transform: `translate3d(${transform.x}px, ${transform.y}px, 0)`,
  } : undefined

  const isArchived = tree.archived === 1

  const classes = [
    'rhizome-card',
    isSelected ? 'rhizome-card--selected' : '',
    isDragging ? 'rhizome-card--dragging' : '',
    isArchived ? 'rhizome-card--archived' : '',
    showCheckboxes ? 'rhizome-card--show-checkboxes' : '',
  ].filter(Boolean).join(' ')

  return (
    <div
      ref={setNodeRef}
      className={classes}
      style={style}
      {...listeners}
      {...attributes}
      onContextMenu={(e) => { e.preventDefault(); onContextMenu(e, tree.rhizome_id) }}
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey) {
          onSelect(tree.rhizome_id, e)
        } else {
          onClick(tree.rhizome_id)
        }
      }}
    >
      {/* Checkbox */}
      <span
        className={`rhizome-card-checkbox ${isSelected ? 'checked' : ''}`}
        onClick={(e) => {
          e.stopPropagation()
          onSelect(tree.rhizome_id, e)
        }}
      >
        {isSelected ? '\u2713' : ''}
      </span>

      {/* Title */}
      <span className="rhizome-card-title">{tree.title || 'Untitled'}</span>

      {/* Meta row: date + tags */}
      <span className="rhizome-card-meta">
        <span className="rhizome-card-date">
          {new Date(tree.updated_at).toLocaleDateString()}
        </span>
        {isArchived && <span className="rhizome-card-archived-label">archived</span>}
        {tree.tags.length > 0 && (
          <span className="rhizome-card-tags">
            {tree.tags.map(t => (
              <span
                key={t}
                className="rhizome-card-tag-dot"
                style={{ background: tagColor(t) }}
                title={t}
              />
            ))}
          </span>
        )}
      </span>

      {/* Folder chips + archive action */}
      <span className="rhizome-card-bottom">
        {tree.folders.length > 0 && (
          <span className="rhizome-card-folders">
            {tree.folders.map(f => (
              <span key={f} className="rhizome-card-folder-chip">
                {f.split('/').pop()}
                <button
                  onClick={(e) => { e.stopPropagation(); onRemoveFolder(tree.rhizome_id, f) }}
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
            className="rhizome-card-archive-btn"
            onClick={(e) => { e.stopPropagation(); onUnarchive(tree.rhizome_id) }}
            title="Unarchive"
          >
            Unarchive
          </button>
        ) : (
          <button
            className="rhizome-card-archive-btn"
            onClick={(e) => { e.stopPropagation(); onArchive(tree.rhizome_id) }}
            title="Archive"
          >
            Archive
          </button>
        )}
      </span>
    </div>
  )
}
