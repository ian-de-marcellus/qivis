import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getInterventions } from '../../api/client.ts'
import type { InterventionEntry, NodeResponse } from '../../api/types.ts'
import type { TreeDefaults } from '../TreeView/contextDiffs.ts'
import { CanvasBubble } from './CanvasBubble.tsx'
import { computeCanvasGrid } from './eraComputation.ts'
import './CanvasView.css'

interface CanvasViewProps {
  treeId: string
  pathNodes: NodeResponse[]
  treeDefaults: TreeDefaults
  onDismiss: () => void
}

export function CanvasView({ treeId, pathNodes, treeDefaults, onDismiss }: CanvasViewProps) {
  const [interventions, setInterventions] = useState<InterventionEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const headerRef = useRef<HTMLDivElement>(null)
  const bodyRef = useRef<HTMLDivElement>(null)

  // Fetch interventions on mount
  useEffect(() => {
    let cancelled = false
    getInterventions(treeId)
      .then((resp) => {
        if (!cancelled) setInterventions(resp.interventions)
      })
      .catch((err) => {
        if (!cancelled) setError(String(err))
      })
    return () => { cancelled = true }
  }, [treeId])

  // Escape to dismiss
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onDismiss()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [onDismiss])

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) {
      onDismiss()
    }
  }

  // Sync horizontal scroll from body to era header strip
  const handleBodyScroll = useCallback(() => {
    if (bodyRef.current && headerRef.current) {
      headerRef.current.scrollLeft = bodyRef.current.scrollLeft
    }
  }, [])

  // Detect exclusion state changes between consecutive generated nodes.
  // Only creates synthetic interventions when the exclusion set actually differs
  // between two assistant nodes (i.e. a generation saw different context).
  const combinedInterventions = useMemo(() => {
    if (interventions == null) return null

    const synthetic: InterventionEntry[] = []
    const assistantNodes = pathNodes.filter((n) => n.role === 'assistant')

    let prevExcludedIds: string[] = []
    for (const node of assistantNodes) {
      const excludedIds = node.context_usage?.excluded_node_ids ?? []
      const prevSet = new Set(prevExcludedIds)
      const currSet = new Set(excludedIds)

      const changed =
        prevSet.size !== currSet.size ||
        excludedIds.some((id) => !prevSet.has(id)) ||
        prevExcludedIds.some((id) => !currSet.has(id))

      if (changed && (prevExcludedIds.length > 0 || excludedIds.length > 0)) {
        synthetic.push({
          event_id: `synthetic-excl-${node.node_id}`,
          sequence_num: -1,
          timestamp: node.created_at,
          intervention_type: 'exclusion_changed',
          node_id: null,
          original_content: null,
          new_content: null,
          old_value: JSON.stringify(prevExcludedIds),
          new_value: JSON.stringify(excludedIds),
        })
      }
      prevExcludedIds = excludedIds
    }

    // Merge synthetic into real interventions, sort by timestamp
    const combined = [...interventions, ...synthetic]
    combined.sort((a, b) => a.timestamp.localeCompare(b.timestamp))
    return combined
  }, [interventions, pathNodes])

  // Compute grid
  const grid = useMemo(() => {
    if (combinedInterventions == null) return null
    return computeCanvasGrid(pathNodes, combinedInterventions, treeDefaults)
  }, [pathNodes, combinedInterventions, treeDefaults])

  // Format era header timestamp
  const formatEraTimestamp = (iso: string): string => {
    const date = new Date(iso)
    return date.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
    }) + ' ' + date.toLocaleTimeString(undefined, {
      hour: 'numeric',
      minute: '2-digit',
    })
  }

  // Era header subtitle: what changed
  const eraSubtitle = (intervention: InterventionEntry): string => {
    if (intervention.intervention_type === 'system_prompt_changed') {
      return 'system prompt'
    }
    if (intervention.intervention_type === 'node_edited' && intervention.node_id) {
      const node = pathNodes.find(n => n.node_id === intervention.node_id)
      if (node) {
        const idx = pathNodes.indexOf(node)
        return `${node.role} #${idx + 1}`
      }
    }
    if (intervention.intervention_type === 'exclusion_changed') {
      try {
        const ids: string[] = JSON.parse(intervention.new_value ?? '[]')
        return ids.length > 0 ? `${ids.length} excluded` : 'exclusions cleared'
      } catch {
        return 'exclusions'
      }
    }
    return ''
  }

  // Role label abbreviation
  const roleLabel = (role: string): string => {
    if (role === 'system') return 'sys'
    if (role === 'assistant') return 'asst'
    if (role === 'researcher_note') return 'note'
    return role
  }

  return (
    <div className="canvas-backdrop" onClick={handleBackdropClick}>
      <div className="canvas-view" role="dialog" aria-label="Palimpsest View">

        {/* Title bar */}
        <div className="canvas-header">
          <div className="canvas-header-left">
            <span className="canvas-title">Palimpsest</span>
            <span className="canvas-subtitle">
              {pathNodes.length} messages
              {grid && grid.eras.length > 1 && ` \u00b7 ${grid.eras.length - 1} intervention${grid.eras.length > 2 ? 's' : ''}`}
            </span>
          </div>
          <button className="canvas-close" onClick={onDismiss}>Close</button>
        </div>

        {/* Loading / Error states */}
        {interventions == null && !error && (
          <div className="canvas-loading">Loading interventions...</div>
        )}
        {error && (
          <div className="canvas-error">{error}</div>
        )}

        {grid && (
          <>
            {/* Era headers — outside scroll container, synced horizontally */}
            <div className="canvas-era-strip" ref={headerRef}>
              <div className="canvas-era-strip-gutter" />
              <div className="canvas-era-strip-cells">
                {grid.eras.map((era) => (
                  <div key={era.index} className="canvas-era-header">
                    <div className="canvas-era-label">{era.label}</div>
                    {era.timestamp && (
                      <div className="canvas-era-timestamp">{formatEraTimestamp(era.timestamp)}</div>
                    )}
                    {era.intervention && (
                      <div className="canvas-era-subtitle">{eraSubtitle(era.intervention)}</div>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* Scrollable body — message rows */}
            <div className="canvas-body" ref={bodyRef} onScroll={handleBodyScroll}>
              {grid.rowLabels.map((row, rowIdx) => (
                <div key={`row-${rowIdx}`} className="canvas-row">
                  <div className="canvas-row-gutter">
                    <span className="canvas-row-role">
                      {roleLabel(row.role)}
                      {row.index > 0 && (
                        <span className="canvas-row-index">{row.index}</span>
                      )}
                    </span>
                  </div>

                  <div className="canvas-row-cells">
                    {grid.eras.map((era) => (
                      <div
                        key={era.index}
                        className={
                          'canvas-era-cell' +
                          (rowIdx > era.lastActiveRow ? ' beyond-era' : '')
                        }
                      >
                        <CanvasBubble
                          cell={era.cells[rowIdx]}
                          isFirstEra={era.index === 0}
                        />
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
