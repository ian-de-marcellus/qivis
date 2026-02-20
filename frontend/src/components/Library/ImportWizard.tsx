import { useCallback, useRef, useState } from 'react'
import * as api from '../../api/client.ts'
import type { ConversationPreview, ImportResult } from '../../api/types.ts'
import { useTreeStore } from '../../store/treeStore.ts'
import './ImportWizard.css'

type WizardState = 'idle' | 'previewing' | 'preview' | 'importing' | 'done' | 'error'

interface ImportWizardProps {
  onDismiss: () => void
}

export function ImportWizard({ onDismiss }: ImportWizardProps) {
  const [state, setState] = useState<WizardState>('idle')
  const [file, setFile] = useState<File | null>(null)
  const [formatDetected, setFormatDetected] = useState('')
  const [conversations, setConversations] = useState<ConversationPreview[]>([])
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [results, setResults] = useState<ImportResult[]>([])
  const [error, setError] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const fetchTrees = useTreeStore(s => s.fetchTrees)
  const selectTree = useTreeStore(s => s.selectTree)

  const handleFile = useCallback(async (f: File) => {
    setFile(f)
    setState('previewing')
    setError('')
    try {
      const preview = await api.previewImport(f)
      setFormatDetected(preview.format_detected)
      setConversations(preview.conversations)
      setSelected(new Set(preview.conversations.map(c => c.index)))
      setState('preview')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setState('error')
    }
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const f = e.dataTransfer.files[0]
    if (f) handleFile(f)
  }, [handleFile])

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(true)
  }, [])

  const handleDragLeave = useCallback(() => {
    setDragOver(false)
  }, [])

  const handleFileInput = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (f) handleFile(f)
  }, [handleFile])

  const toggleConversation = useCallback((index: number) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(index)) {
        next.delete(index)
      } else {
        next.add(index)
      }
      return next
    })
  }, [])

  const handleImport = useCallback(async () => {
    if (!file || selected.size === 0) return
    setState('importing')
    try {
      const resp = await api.importConversations(file, {
        selected: [...selected].sort((a, b) => a - b),
      })
      setResults(resp.results)
      setState('done')
      fetchTrees()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setState('error')
    }
  }, [file, selected, fetchTrees])

  const handleGoToTree = useCallback((treeId: string) => {
    selectTree(treeId)
    onDismiss()
  }, [selectTree, onDismiss])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Escape') onDismiss()
  }, [onDismiss])

  const handleBackdropClick = useCallback((e: React.MouseEvent) => {
    if (e.target === e.currentTarget) onDismiss()
  }, [onDismiss])

  return (
    <div className="import-backdrop" onClick={handleBackdropClick} onKeyDown={handleKeyDown}>
      <div className="import-wizard" role="dialog" aria-label="Import conversations">
        <div className="import-header">
          <h3>Import Conversations</h3>
          <button className="import-close" onClick={onDismiss} aria-label="Close">&times;</button>
        </div>

        {state === 'idle' && (
          <div
            className={`import-dropzone${dragOver ? ' drag-over' : ''}`}
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onClick={() => fileInputRef.current?.click()}
          >
            <div className="dropzone-label">
              Drop a .json file here, or click to browse
            </div>
            <div className="dropzone-hint">
              Supports ChatGPT export (conversations.json) and ShareGPT format
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".json"
              onChange={handleFileInput}
              hidden
            />
          </div>
        )}

        {state === 'previewing' && (
          <div className="import-status">Parsing {file?.name}...</div>
        )}

        {state === 'preview' && (
          <div className="import-preview">
            <div className="preview-meta">
              <span className="format-badge">{formatDetected}</span>
              <span className="conv-count">
                {conversations.length} conversation{conversations.length !== 1 ? 's' : ''} found
              </span>
            </div>

            <div className="preview-list">
              {conversations.map(conv => (
                <label key={conv.index} className="preview-item">
                  <input
                    type="checkbox"
                    checked={selected.has(conv.index)}
                    onChange={() => toggleConversation(conv.index)}
                  />
                  <div className="preview-item-body">
                    <div className="preview-item-title">
                      {conv.title || 'Untitled'}
                    </div>
                    <div className="preview-item-meta">
                      {conv.message_count} messages
                      {conv.has_branches && ` \u00b7 ${conv.branch_count} fork${conv.branch_count !== 1 ? 's' : ''}`}
                      {conv.model_names.length > 0 && ` \u00b7 ${conv.model_names.join(', ')}`}
                    </div>
                    {conv.system_prompt_preview && (
                      <div className="preview-item-system">
                        {conv.system_prompt_preview}
                      </div>
                    )}
                    {conv.first_messages.length > 0 && (
                      <div className="preview-item-messages">
                        {conv.first_messages.slice(0, 3).map((m, i) => (
                          <div key={i} className="preview-message">
                            <span className={`preview-role ${m.role}`}>{m.role}</span>
                            {m.content_preview.slice(0, 120)}
                            {m.content_preview.length > 120 ? '...' : ''}
                          </div>
                        ))}
                      </div>
                    )}
                    {conv.warnings.length > 0 && (
                      <div className="preview-warnings">
                        {conv.warnings.map((w, i) => (
                          <div key={i} className="preview-warning">{w}</div>
                        ))}
                      </div>
                    )}
                  </div>
                </label>
              ))}
            </div>

            <div className="import-actions">
              <button
                className="import-btn-primary"
                onClick={handleImport}
                disabled={selected.size === 0}
              >
                Import {selected.size} conversation{selected.size !== 1 ? 's' : ''}
              </button>
              <button className="import-btn-secondary" onClick={onDismiss}>Cancel</button>
            </div>
          </div>
        )}

        {state === 'importing' && (
          <div className="import-status">Importing...</div>
        )}

        {state === 'done' && (
          <div className="import-done">
            <div className="done-summary">
              Imported {results.length} conversation{results.length !== 1 ? 's' : ''}
            </div>
            <div className="done-list">
              {results.map(r => (
                <div key={r.tree_id} className="done-item">
                  <span className="done-title">{r.title || 'Untitled'}</span>
                  <span className="done-count">{r.node_count} messages</span>
                  <button
                    className="done-go"
                    onClick={() => handleGoToTree(r.tree_id)}
                  >
                    Open
                  </button>
                </div>
              ))}
            </div>
            <div className="import-actions">
              <button className="import-btn-secondary" onClick={onDismiss}>Close</button>
            </div>
          </div>
        )}

        {state === 'error' && (
          <div className="import-error">
            <div className="error-message">{error}</div>
            <div className="import-actions">
              <button
                className="import-btn-secondary"
                onClick={() => {
                  setState('idle')
                  setFile(null)
                  setError('')
                }}
              >
                Try again
              </button>
              <button className="import-btn-secondary" onClick={onDismiss}>Close</button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
