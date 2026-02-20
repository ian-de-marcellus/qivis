import { useEffect, useState } from 'react'
import { useTreeStore, useTreeData } from '../../store/treeStore.ts'
import { ImportWizard } from './ImportWizard.tsx'
import './TreeList.css'

export function TreeList() {
  const { trees, selectedTreeId, providers, isLoading } = useTreeData()
  const selectTree = useTreeStore(s => s.selectTree)
  const createTree = useTreeStore(s => s.createTree)
  const fetchProviders = useTreeStore(s => s.fetchProviders)
  const [isCreating, setIsCreating] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [newSystemPrompt, setNewSystemPrompt] = useState('')
  const [showSettings, setShowSettings] = useState(false)
  const [newProvider, setNewProvider] = useState('')
  const [newModel, setNewModel] = useState('')
  const [newIncludeTimestamps, setNewIncludeTimestamps] = useState(true)
  const [newStreamResponses, setNewStreamResponses] = useState(true)
  const [showImport, setShowImport] = useState(false)

  useEffect(() => {
    if (isCreating) fetchProviders()
  }, [isCreating, fetchProviders])

  const selectedProvider = providers.find((p) => p.name === newProvider)
  const suggestedModels = selectedProvider?.models ?? []

  const sorted = [...trees].sort(
    (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
  )

  const handleCreate = async () => {
    if (!newTitle.trim()) return
    await createTree(newTitle.trim(), {
      systemPrompt: newSystemPrompt.trim() || undefined,
      defaultProvider: newProvider || undefined,
      defaultModel: newModel || undefined,
      metadata: {
        include_timestamps: newIncludeTimestamps,
        stream_responses: newStreamResponses,
      },
    })
    setNewTitle('')
    setNewSystemPrompt('')
    setNewProvider('')
    setNewModel('')
    setNewIncludeTimestamps(true)
    setNewStreamResponses(true)
    setShowSettings(false)
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
        <div className="tree-list-header-actions">
          <button
            className="import-tree-btn"
            onClick={() => setShowImport(true)}
            disabled={isLoading}
          >
            Import
          </button>
          <button
            className="new-tree-btn"
            onClick={() => setIsCreating(!isCreating)}
            disabled={isLoading}
          >
            {isCreating ? 'Cancel' : '+ New'}
          </button>
        </div>
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

          <button
            type="button"
            className="create-settings-toggle"
            onClick={() => setShowSettings(!showSettings)}
          >
            <span className={`toggle-arrow ${showSettings ? 'expanded' : ''}`}>&#9654;</span>
            <span>Defaults</span>
          </button>

          {showSettings && (
            <div className="create-settings">
              <div className="create-setting-row">
                <label>Provider</label>
                {providers.length > 0 ? (
                  <select
                    value={newProvider}
                    onChange={(e) => {
                      setNewProvider(e.target.value)
                      setNewModel('')
                    }}
                  >
                    <option value="">Default</option>
                    {providers.map((p) => (
                      <option key={p.name} value={p.name}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                ) : (
                  <select disabled>
                    <option>Loading...</option>
                  </select>
                )}
              </div>
              <div className="create-setting-row">
                <label>Model</label>
                <input
                  type="text"
                  value={newModel}
                  onChange={(e) => setNewModel(e.target.value)}
                  placeholder={suggestedModels[0] ?? 'default'}
                  list="create-model-suggestions"
                />
                <datalist id="create-model-suggestions">
                  {suggestedModels.map((m) => (
                    <option key={m} value={m} />
                  ))}
                </datalist>
              </div>
              <div className="create-setting-toggle">
                <label>
                  <input
                    type="checkbox"
                    checked={newIncludeTimestamps}
                    onChange={(e) => setNewIncludeTimestamps(e.target.checked)}
                  />
                  Include timestamps in context
                </label>
              </div>
              <div className="create-setting-toggle">
                <label>
                  <input
                    type="checkbox"
                    checked={newStreamResponses}
                    onChange={(e) => setNewStreamResponses(e.target.checked)}
                  />
                  Stream responses
                </label>
              </div>
            </div>
          )}

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
      {showImport && <ImportWizard onDismiss={() => setShowImport(false)} />}
    </div>
  )
}
