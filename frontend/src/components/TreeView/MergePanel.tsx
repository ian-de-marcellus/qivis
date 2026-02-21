import { useCallback, useRef, useState } from 'react'
import * as api from '../../api/client.ts'
import type { MergePreviewResponse, MergeResult } from '../../api/types.ts'
import { useTreeStore } from '../../store/treeStore.ts'
import './MergePanel.css'

type MergeState = 'idle' | 'previewing' | 'preview' | 'merging' | 'done' | 'error'

interface MergePanelProps {
  treeId: string
  onClose: () => void
}

export function MergePanel({ treeId, onClose }: MergePanelProps) {
  const [state, setState] = useState<MergeState>('idle')
  const [preview, setPreview] = useState<MergePreviewResponse | null>(null)
  const [result, setResult] = useState<MergeResult | null>(null)
  const [error, setError] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const selectTree = useTreeStore(s => s.selectTree)
  const navigateToNode = useTreeStore(s => s.navigateToNode)

  const handleFile = useCallback(async (f: File) => {
    setFile(f)
    setState('previewing')
    setError('')
    try {
      const prev = await api.previewMerge(treeId, f)
      setPreview(prev)
      setState('preview')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setState('error')
    }
  }, [treeId])

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

  const handleMerge = useCallback(async () => {
    if (!file) return
    setState('merging')
    setError('')
    try {
      const res = await api.executeMerge(treeId, file)
      setResult(res)
      setState('done')
      // Refresh the tree to show new nodes
      await selectTree(treeId)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setState('error')
    }
  }, [treeId, file, selectTree])

  const handleNavigate = useCallback(() => {
    if (result?.node_ids[0]) {
      navigateToNode(result.node_ids[0])
      onClose()
    }
  }, [result, navigateToNode, onClose])

  const handleReset = useCallback(() => {
    setState('idle')
    setPreview(null)
    setResult(null)
    setFile(null)
    setError('')
    if (fileInputRef.current) fileInputRef.current.value = ''
  }, [])

  return (
    <div className="merge-panel">
      <div className="merge-panel-header">
        <span className="merge-panel-title">Merge conversation</span>
        <button className="merge-panel-close" onClick={onClose}>Close</button>
      </div>

      <div className="merge-panel-body">
        {/* Idle: file drop zone */}
        {state === 'idle' && (
          <div
            className={`merge-dropzone${dragOver ? ' drag-over' : ''}`}
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onClick={() => fileInputRef.current?.click()}
          >
            <div className="merge-dropzone-label">
              Drop a conversation file here, or click to browse
            </div>
            <div className="merge-dropzone-hint">
              Supports ChatGPT, Claude.ai, and ShareGPT exports (.json)
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

        {/* Previewing: loading */}
        {state === 'previewing' && (
          <div className="merge-status">Analyzing file...</div>
        )}

        {/* Preview: show match results */}
        {state === 'preview' && preview && (
          <div className="merge-preview">
            <div className="merge-preview-summary">
              <span className="merge-format-badge">{preview.source_format}</span>
              {preview.source_title && (
                <span className="merge-source-title">{preview.source_title}</span>
              )}
            </div>

            <div className="merge-counts">
              <div className="merge-count">
                <span className="merge-count-num">{preview.matched_count}</span>
                <span className="merge-count-label">matched</span>
              </div>
              <div className="merge-count merge-count-new">
                <span className="merge-count-num">{preview.new_count}</span>
                <span className="merge-count-label">new</span>
              </div>
            </div>

            {preview.graft_points.length > 0 && (
              <div className="merge-graft-points">
                {preview.graft_points.map((gp, i) => (
                  <div key={i} className="merge-graft-point">
                    <span className="merge-graft-count">{gp.new_node_count} new</span>
                    {gp.parent_content_preview ? (
                      <span className="merge-graft-after">
                        after &ldquo;{gp.parent_content_preview.slice(0, 60)}
                        {(gp.parent_content_preview.length > 60) && '...'}
                        &rdquo;
                      </span>
                    ) : (
                      <span className="merge-graft-after">as new root</span>
                    )}
                  </div>
                ))}
              </div>
            )}

            {preview.warnings.length > 0 && (
              <div className="merge-warnings">
                {preview.warnings.map((w, i) => (
                  <div key={i} className="merge-warning">{w}</div>
                ))}
              </div>
            )}

            {preview.new_count > 0 ? (
              <button className="merge-submit-btn" onClick={handleMerge}>
                Merge {preview.new_count} message{preview.new_count !== 1 && 's'}
              </button>
            ) : (
              <div className="merge-nothing">
                Nothing to merge — all messages already exist in this tree.
              </div>
            )}
          </div>
        )}

        {/* Merging: progress */}
        {state === 'merging' && (
          <div className="merge-status">Merging...</div>
        )}

        {/* Done: results */}
        {state === 'done' && result && (
          <div className="merge-done">
            <div className="merge-done-message">
              Added {result.created_count} message{result.created_count !== 1 && 's'}
              {result.matched_count > 0 && (
                <> ({result.matched_count} already existed)</>
              )}
            </div>
            <div className="merge-done-actions">
              {result.node_ids.length > 0 && (
                <button className="merge-submit-btn" onClick={handleNavigate}>
                  Go to new messages
                </button>
              )}
              <button className="merge-secondary-btn" onClick={handleReset}>
                Merge another
              </button>
            </div>
          </div>
        )}

        {/* Error */}
        {state === 'error' && (
          <div className="merge-error">
            <div className="merge-error-message">{error}</div>
            <button className="merge-secondary-btn" onClick={handleReset}>
              Try again
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
