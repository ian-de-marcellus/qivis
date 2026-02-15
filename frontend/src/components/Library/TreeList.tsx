import { useState } from 'react'
import { useTreeStore } from '../../store/treeStore.ts'
import './TreeList.css'

export function TreeList() {
  const { trees, selectedTreeId, selectTree, createTree, isLoading } = useTreeStore()
  const [isCreating, setIsCreating] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [newSystemPrompt, setNewSystemPrompt] = useState('')

  const sorted = [...trees].sort(
    (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
  )

  const handleCreate = async () => {
    if (!newTitle.trim()) return
    await createTree(newTitle.trim(), newSystemPrompt.trim() || undefined)
    setNewTitle('')
    setNewSystemPrompt('')
    setIsCreating(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleCreate()
    } else if (e.key === 'Escape') {
      setIsCreating(false)
    }
  }

  return (
    <div className="tree-list">
      <div className="tree-list-header">
        <h2>Trees</h2>
        <button
          className="new-tree-btn"
          onClick={() => setIsCreating(!isCreating)}
          disabled={isLoading}
        >
          {isCreating ? 'Cancel' : '+ New'}
        </button>
      </div>

      {isCreating && (
        <div className="new-tree-form">
          <input
            type="text"
            placeholder="Tree title..."
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            onKeyDown={handleKeyDown}
            autoFocus
          />
          <textarea
            placeholder="System prompt (optional)..."
            value={newSystemPrompt}
            onChange={(e) => setNewSystemPrompt(e.target.value)}
            rows={2}
          />
          <button onClick={handleCreate} disabled={!newTitle.trim()}>
            Create
          </button>
        </div>
      )}

      <div className="tree-items">
        {sorted.map((tree) => (
          <button
            key={tree.tree_id}
            className={`tree-item ${tree.tree_id === selectedTreeId ? 'selected' : ''}`}
            onClick={() => selectTree(tree.tree_id)}
          >
            <span className="tree-title">{tree.title || 'Untitled'}</span>
            <span className="tree-date">
              {new Date(tree.updated_at).toLocaleDateString()}
            </span>
          </button>
        ))}
        {sorted.length === 0 && !isLoading && (
          <p className="tree-empty">No trees yet. Create one to start.</p>
        )}
      </div>
    </div>
  )
}
