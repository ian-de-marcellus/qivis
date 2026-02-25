import { useCallback, useEffect, useMemo, useState } from 'react'
import { useRhizomeStore, useRhizomeData } from '../../store/rhizomeStore.ts'
import type { RhizomeSummary } from '../../api/types.ts'
import { tagColor } from '../../utils/tagColor.ts'
import { type FolderNode, buildFolderTrie, countRhizomesInFolder } from '../../utils/folderTrie.ts'
import { RhizomeContextMenu } from './RhizomeContextMenu.tsx'
import { ImportWizard } from './ImportWizard.tsx'
import './RhizomeList.css'

type ViewMode = 'all' | 'folders'

const VIEW_MODE_KEY = 'qivis-view-mode'
const COLLAPSED_KEY = 'qivis-collapsed-folders'

function getStoredViewMode(): ViewMode {
  const stored = localStorage.getItem(VIEW_MODE_KEY)
  return stored === 'folders' ? 'folders' : 'all'
}

function getStoredCollapsed(): Set<string> {
  try {
    const stored = localStorage.getItem(COLLAPSED_KEY)
    return stored ? new Set(JSON.parse(stored)) : new Set()
  } catch {
    return new Set()
  }
}

export function RhizomeList() {
  const { rhizomes, selectedRhizomeId, providers, isLoading } = useRhizomeData()
  const selectRhizome = useRhizomeStore(s => s.selectRhizome)
  const createRhizome = useRhizomeStore(s => s.createRhizome)
  const updateRhizome = useRhizomeStore(s => s.updateRhizome)
  const fetchRhizomes = useRhizomeStore(s => s.fetchRhizomes)
  const fetchProviders = useRhizomeStore(s => s.fetchProviders)
  const [isCreating, setIsCreating] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [newGenerationMode, setNewGenerationMode] = useState<'chat' | 'completion'>('chat')
  const [newSystemPrompt, setNewSystemPrompt] = useState('')
  const [newPromptTemplate, setNewPromptTemplate] = useState('raw')
  const [showSettings, setShowSettings] = useState(false)
  const [newProvider, setNewProvider] = useState('')
  const [newModel, setNewModel] = useState('')
  const [newIncludeTimestamps, setNewIncludeTimestamps] = useState(true)
  const [newStreamResponses, setNewStreamResponses] = useState(true)
  const [showImport, setShowImport] = useState(false)

  // New state for organization
  const [viewMode, setViewMode] = useState<ViewMode>(getStoredViewMode)
  const [collapsedFolders, setCollapsedFolders] = useState<Set<string>>(getStoredCollapsed)
  const [activeTagFilters, setActiveTagFilters] = useState<string[]>([])
  const [showArchived, setShowArchived] = useState(false)
  const [contextMenu, setContextMenu] = useState<{
    treeId: string; x: number; y: number
  } | null>(null)
  const [editingTreeId, setEditingTreeId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')

  useEffect(() => {
    if (isCreating) fetchProviders()
  }, [isCreating, fetchProviders])

  // Persist view mode and collapsed state
  useEffect(() => {
    localStorage.setItem(VIEW_MODE_KEY, viewMode)
  }, [viewMode])

  useEffect(() => {
    localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...collapsedFolders]))
  }, [collapsedFolders])

  // Refetch trees when showArchived changes
  useEffect(() => {
    fetchRhizomes(showArchived)
  }, [showArchived, fetchRhizomes])

  const selectedProvider = providers.find((p) => p.name === newProvider)
  const suggestedModels = selectedProvider?.models ?? []

  // Filter rhizomes by active tag filters
  const filteredRhizomes = useMemo(() => {
    if (activeTagFilters.length === 0) return rhizomes
    return rhizomes.filter(t =>
      activeTagFilters.every(tag => t.tags.includes(tag)),
    )
  }, [rhizomes, activeTagFilters])

  // Sort by updated_at
  const sorted = useMemo(() =>
    [...filteredRhizomes].sort(
      (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
    ),
  [filteredRhizomes])

  const treeMap = useMemo(() =>
    new Map(sorted.map(t => [t.rhizome_id, t])),
  [sorted])

  // Derive all tags from visible rhizomes for the filter bar
  const allTags = useMemo(() =>
    [...new Set(rhizomes.flatMap(t => t.tags))].sort(),
  [rhizomes])

  // Folder trie for folder view
  const folderTrie = useMemo(() => buildFolderTrie(sorted), [sorted])

  // Trees with no folders (for "Unsorted" group)
  const unsortedTrees = useMemo(() =>
    sorted.filter(t => t.folders.length === 0),
  [sorted])

  const handleCreate = async () => {
    if (!newTitle.trim()) return
    await createRhizome(newTitle.trim(), {
      systemPrompt: newGenerationMode === 'chat' ? (newSystemPrompt.trim() || undefined) : undefined,
      defaultProvider: newProvider || undefined,
      defaultModel: newModel || undefined,
      metadata: {
        generation_mode: newGenerationMode,
        ...(newGenerationMode === 'completion' && { prompt_template: newPromptTemplate }),
        include_timestamps: newGenerationMode === 'chat' && newIncludeTimestamps,
        stream_responses: newStreamResponses,
      },
    })
    setNewTitle('')
    setNewGenerationMode('chat')
    setNewSystemPrompt('')
    setNewPromptTemplate('raw')
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

  const handleContextMenu = useCallback((e: React.MouseEvent, treeId: string) => {
    e.preventDefault()
    setContextMenu({ treeId, x: e.clientX, y: e.clientY })
  }, [])

  const handleRenameStart = useCallback((treeId: string) => {
    const rhizome = rhizomes.find(t => t.rhizome_id === treeId)
    setEditingTreeId(treeId)
    setEditTitle(rhizome?.title ?? '')
  }, [rhizomes])

  const handleRenameCommit = useCallback(async () => {
    if (!editingTreeId) return
    const trimmed = editTitle.trim()
    if (trimmed) {
      await updateRhizome(editingTreeId, { title: trimmed })
    }
    setEditingTreeId(null)
    setEditTitle('')
  }, [editingTreeId, editTitle, updateRhizome])

  const toggleFolder = useCallback((path: string) => {
    setCollapsedFolders(prev => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }, [])

  const toggleTagFilter = useCallback((tag: string) => {
    setActiveTagFilters(prev =>
      prev.includes(tag) ? prev.filter(t => t !== tag) : [...prev, tag],
    )
  }, [])

  // Render a single tree item (shared between flat and folder views)
  const renderTreeItem = (tree: RhizomeSummary) => {
    const isEditing = editingTreeId === tree.rhizome_id
    const isArchived = tree.archived === 1

    return (
      <button
        key={tree.rhizome_id}
        className={`rhizome-item ${tree.rhizome_id === selectedRhizomeId ? 'selected' : ''} ${isArchived ? 'archived' : ''}`}
        onClick={() => !isEditing && selectRhizome(tree.rhizome_id)}
        onContextMenu={(e) => handleContextMenu(e, tree.rhizome_id)}
        onDoubleClick={() => handleRenameStart(tree.rhizome_id)}
      >
        <span className="rhizome-item-main">
          {isEditing ? (
            <input
              className="rhizome-rename-input"
              type="text"
              value={editTitle}
              onChange={e => setEditTitle(e.target.value)}
              onBlur={handleRenameCommit}
              onKeyDown={e => {
                if (e.key === 'Enter') handleRenameCommit()
                else if (e.key === 'Escape') {
                  setEditingTreeId(null)
                  setEditTitle('')
                }
                e.stopPropagation()
              }}
              onClick={e => e.stopPropagation()}
              autoFocus
            />
          ) : (
            <span className="rhizome-title">{tree.title || 'Untitled'}</span>
          )}
          {tree.tags.length > 0 && (
            <span className="rhizome-tag-dots">
              {tree.tags.map(t => (
                <span
                  key={t}
                  className="rhizome-tag-dot"
                  style={{ background: tagColor(t) }}
                  title={t}
                />
              ))}
            </span>
          )}
        </span>
        <span className="rhizome-date">
          {new Date(tree.updated_at).toLocaleDateString()}
          {isArchived && <span className="rhizome-archived-label">archived</span>}
        </span>
      </button>
    )
  }

  // Render folder tree recursively
  const renderFolderNode = (node: FolderNode, depth: number) => {
    const isCollapsed = collapsedFolders.has(node.path)
    const count = countRhizomesInFolder(node, treeMap)
    if (count === 0) return null

    return (
      <div key={node.path} className="folder-group">
        <button
          className="folder-header"
          style={{ paddingLeft: `calc(${var_space_md} + ${depth * 16}px)` }}
          onClick={() => toggleFolder(node.path)}
        >
          <span className={`folder-chevron ${isCollapsed ? '' : 'expanded'}`}>&#9654;</span>
          <span className="folder-name">{node.name}</span>
          <span className="folder-count">{count}</span>
        </button>
        {!isCollapsed && (
          <>
            {node.rhizomeIds
              .map(id => treeMap.get(id))
              .filter((t): t is RhizomeSummary => t != null)
              .map(renderTreeItem)}
            {node.children.map(child => renderFolderNode(child, depth + 1))}
          </>
        )}
      </div>
    )
  }

  // CSS variable reference for paddingLeft computation
  const var_space_md = 'var(--space-md)'

  return (
    <div className="rhizome-list">
      <div className="rhizome-list-header">
        <h2>Trees</h2>
        <div className="rhizome-list-header-actions">
          <button
            className={`view-mode-btn ${viewMode === 'all' ? 'active' : ''}`}
            onClick={() => setViewMode('all')}
            title="Flat list"
          >
            &#9776;
          </button>
          <button
            className={`view-mode-btn ${viewMode === 'folders' ? 'active' : ''}`}
            onClick={() => setViewMode('folders')}
            title="Folder view"
          >
            &#128193;
          </button>
          <button
            className="import-rhizome-btn"
            onClick={() => setShowImport(true)}
            disabled={isLoading}
          >
            Import
          </button>
          <button
            className="new-rhizome-btn"
            onClick={() => setIsCreating(!isCreating)}
            disabled={isLoading}
          >
            {isCreating ? 'Cancel' : '+ New'}
          </button>
        </div>
      </div>

      {/* Tag filter bar */}
      {allTags.length > 0 && (
        <div className="tag-filter-bar">
          {allTags.map(tag => (
            <button
              key={tag}
              className={`tag-filter-pill ${activeTagFilters.includes(tag) ? 'active' : ''}`}
              style={{
                borderColor: tagColor(tag),
                ...(activeTagFilters.includes(tag) ? { background: tagColor(tag), color: '#fff' } : {}),
              }}
              onClick={() => toggleTagFilter(tag)}
            >
              <span className="tag-filter-dot" style={{ background: tagColor(tag) }} />
              {tag}
            </button>
          ))}
        </div>
      )}

      {isCreating && (
        <div className="new-rhizome-form">
          <input
            type="text"
            placeholder="Tree title..."
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            onKeyDown={handleKeyDown}
            autoFocus
          />

          <div className="mode-selector">
            <button
              type="button"
              className={`mode-selector-btn ${newGenerationMode === 'chat' ? 'active' : ''}`}
              onClick={() => setNewGenerationMode('chat')}
            >
              Chat
            </button>
            <button
              type="button"
              className={`mode-selector-btn ${newGenerationMode === 'completion' ? 'active' : ''}`}
              onClick={() => setNewGenerationMode('completion')}
            >
              Completion
            </button>
          </div>

          {newGenerationMode === 'chat' && (
            <textarea
              placeholder="System prompt (optional)..."
              value={newSystemPrompt}
              onChange={(e) => setNewSystemPrompt(e.target.value)}
              rows={2}
            />
          )}

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
              {newGenerationMode === 'completion' && (
                <div className="create-setting-row">
                  <label>Prompt template</label>
                  <select
                    value={newPromptTemplate}
                    onChange={(e) => setNewPromptTemplate(e.target.value)}
                  >
                    <option value="raw">Raw (no template)</option>
                    <option value="alpaca">Alpaca</option>
                    <option value="chatml">ChatML</option>
                    <option value="llama3">Llama 3</option>
                  </select>
                </div>
              )}
              {newGenerationMode === 'chat' && (
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
              )}
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

      <div className="rhizome-items">
        {viewMode === 'all' ? (
          // Flat list
          sorted.map(renderTreeItem)
        ) : (
          // Folder view
          <>
            {folderTrie.map(node => renderFolderNode(node, 0))}
            {unsortedTrees.length > 0 && (
              <div className="folder-group">
                <div className="folder-header unsorted-header">
                  <span className="folder-name">Unsorted</span>
                  <span className="folder-count">{unsortedTrees.length}</span>
                </div>
                {unsortedTrees.map(renderTreeItem)}
              </div>
            )}
          </>
        )}
        {sorted.length === 0 && !isLoading && (
          <p className="rhizome-empty">No trees yet. Create one to start.</p>
        )}
      </div>

      {/* Bottom bar: archive toggle + library button */}
      <div className="archive-toggle-bar">
        <label className="archive-toggle-label">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={e => setShowArchived(e.target.checked)}
          />
          Show archived
        </label>
        <button
          className="library-open-btn"
          onClick={() => useRhizomeStore.getState().setLibraryOpen(true)}
          title="Open library (Cmd+Shift+L)"
        >
          Library
        </button>
      </div>

      {contextMenu && (
        <RhizomeContextMenu
          tree={rhizomes.find(t => t.rhizome_id === contextMenu.treeId)!}
          x={contextMenu.x}
          y={contextMenu.y}
          allTrees={rhizomes}
          onClose={() => setContextMenu(null)}
          onRename={() => handleRenameStart(contextMenu.treeId)}
        />
      )}

      {showImport && <ImportWizard onDismiss={() => setShowImport(false)} />}
    </div>
  )
}
