import { useEffect, useState } from 'react'
import type { PatchTreeRequest } from '../../api/types.ts'
import { useTreeStore } from '../../store/treeStore.ts'
import './TreeSettings.css'

export function TreeSettings() {
  const { currentTree, updateTree, providers, fetchProviders } = useTreeStore()
  const [isOpen, setIsOpen] = useState(false)
  const [isEditingTitle, setIsEditingTitle] = useState(false)

  // Local form state (synced from tree on open/switch)
  const [title, setTitle] = useState('')
  const [provider, setProvider] = useState('')
  const [model, setModel] = useState('')
  const [systemPrompt, setSystemPrompt] = useState('')

  // Sync form state when tree changes or panel opens
  useEffect(() => {
    if (currentTree) {
      setTitle(currentTree.title ?? '')
      setProvider(currentTree.default_provider ?? '')
      setModel(currentTree.default_model ?? '')
      setSystemPrompt(currentTree.default_system_prompt ?? '')
    }
  }, [currentTree?.tree_id, isOpen])

  // Fetch providers when panel opens
  useEffect(() => {
    if (isOpen) fetchProviders()
  }, [isOpen, fetchProviders])

  if (!currentTree) return null

  const selectedProvider = providers.find((p) => p.name === provider)
  const suggestedModels = selectedProvider?.models ?? []

  const hasChanges =
    title !== (currentTree.title ?? '') ||
    provider !== (currentTree.default_provider ?? '') ||
    model !== (currentTree.default_model ?? '') ||
    systemPrompt !== (currentTree.default_system_prompt ?? '')

  const handleSave = async () => {
    if (!hasChanges) return
    const req: PatchTreeRequest = {}
    if (title !== (currentTree.title ?? '')) req.title = title || null
    if (provider !== (currentTree.default_provider ?? ''))
      req.default_provider = provider || null
    if (model !== (currentTree.default_model ?? ''))
      req.default_model = model || null
    if (systemPrompt !== (currentTree.default_system_prompt ?? ''))
      req.default_system_prompt = systemPrompt || null
    await updateTree(currentTree.tree_id, req)
    setIsOpen(false)
  }

  const handleTitleBlur = async () => {
    setIsEditingTitle(false)
    if (title !== (currentTree.title ?? '') && title.trim()) {
      await updateTree(currentTree.tree_id, { title: title.trim() })
    } else {
      setTitle(currentTree.title ?? '')
    }
  }

  const handleTitleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      ;(e.target as HTMLInputElement).blur()
    } else if (e.key === 'Escape') {
      setTitle(currentTree.title ?? '')
      setIsEditingTitle(false)
    }
  }

  return (
    <div className="tree-settings">
      <div className="tree-settings-bar">
        {isEditingTitle ? (
          <input
            className="tree-title-input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={handleTitleBlur}
            onKeyDown={handleTitleKeyDown}
            autoFocus
          />
        ) : (
          <span
            className="tree-title-display"
            onClick={() => setIsEditingTitle(true)}
            title="Click to rename"
          >
            {currentTree.title || 'Untitled'}
          </span>
        )}
        <button
          className={`tree-settings-gear ${isOpen ? 'active' : ''}`}
          onClick={() => setIsOpen(!isOpen)}
          aria-label={isOpen ? 'Close settings' : 'Open settings'}
        >
          <svg viewBox="0 0 20 20" fill="currentColor">
            <path
              fillRule="evenodd"
              d="M8.34 1.804A1 1 0 019.32 1h1.36a1 1 0 01.98.804l.295 1.473c.497.179.971.405 1.416.67l1.4-.587a1 1 0 011.12.272l.962.962a1 1 0 01.272 1.12l-.587 1.4c.265.445.491.919.67 1.416l1.473.295a1 1 0 01.804.98v1.361a1 1 0 01-.804.98l-1.473.295a6.95 6.95 0 01-.67 1.416l.587 1.4a1 1 0 01-.272 1.12l-.962.962a1 1 0 01-1.12.272l-1.4-.587a6.95 6.95 0 01-1.416.67l-.295 1.473a1 1 0 01-.98.804H9.32a1 1 0 01-.98-.804l-.295-1.473a6.95 6.95 0 01-1.416-.67l-1.4.587a1 1 0 01-1.12-.272l-.962-.962a1 1 0 01-.272-1.12l.587-1.4a6.95 6.95 0 01-.67-1.416l-1.473-.295A1 1 0 011 11.68V10.32a1 1 0 01.804-.98l1.473-.295c.179-.497.405-.971.67-1.416l-.587-1.4a1 1 0 01.272-1.12l.962-.962a1 1 0 011.12-.272l1.4.587a6.95 6.95 0 011.416-.67L8.34 1.804zM10 13a3 3 0 100-6 3 3 0 000 6z"
              clipRule="evenodd"
            />
          </svg>
        </button>
      </div>

      {isOpen && (
        <div className="tree-settings-panel">
          <div className="tree-settings-fields">
            <div className="tree-settings-field">
              <label>Default provider</label>
              {providers.length > 0 ? (
                <select
                  value={provider}
                  onChange={(e) => {
                    setProvider(e.target.value)
                    setModel('')
                  }}
                >
                  <option value="">None</option>
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

            <div className="tree-settings-field">
              <label>Default model</label>
              <input
                type="text"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder={suggestedModels[0] ?? 'default'}
                list="tree-settings-model-suggestions"
              />
              <datalist id="tree-settings-model-suggestions">
                {suggestedModels.map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            </div>

            <div className="tree-settings-field">
              <label>Default system prompt</label>
              <textarea
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                placeholder="Enter default system prompt..."
                rows={3}
              />
            </div>

            <div className="tree-settings-toggle">
              <label>
                <input
                  type="checkbox"
                  checked={!!currentTree.metadata?.include_timestamps}
                  onChange={async (e) => {
                    await updateTree(currentTree.tree_id, {
                      metadata: {
                        ...currentTree.metadata,
                        include_timestamps: e.target.checked,
                      },
                    })
                  }}
                />
                Include timestamps in context
              </label>
            </div>

            <div className="tree-settings-actions">
              <button
                className="tree-settings-save"
                onClick={handleSave}
                disabled={!hasChanges}
              >
                Save defaults
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
