import { useState } from 'react'
import * as api from '../../api/client.ts'
import type { EditHistoryEntry, NodeResponse } from '../../api/types.ts'
import { useTreeStore } from '../../store/treeStore.ts'
import './EditHistory.css'

function formatRelativeTime(isoString: string): string {
  const date = new Date(isoString)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMin = Math.floor(diffMs / 60_000)

  if (diffMin < 1) return 'just now'
  if (diffMin < 60) return `${diffMin}m ago`

  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`

  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
  })
}

function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text
  return text.slice(0, maxLen) + '\u2026'
}

interface EditHistoryProps {
  node: NodeResponse
}

export function EditHistory({ node }: EditHistoryProps) {
  const {
    editHistoryCache,
    cacheEditHistory,
    selectedEditVersion,
    setSelectedEditVersion,
    editNodeContent,
  } = useTreeStore()

  const [expanded, setExpanded] = useState(false)
  const [loading, setLoading] = useState(false)

  const cached = editHistoryCache[node.node_id]

  const handleToggle = async () => {
    if (!expanded && !cached) {
      setLoading(true)
      try {
        const resp = await api.getEditHistory(node.tree_id, node.node_id)
        cacheEditHistory(node.node_id, resp.entries)
      } catch {
        // Silently fail — user can retry by collapsing and expanding
      } finally {
        setLoading(false)
      }
    }
    const willCollapse = expanded
    if (willCollapse && selectedEditVersion?.nodeId === node.node_id) {
      setSelectedEditVersion(node.node_id, null)
    }
    setExpanded(!expanded)
  }

  const entries = cached ?? []

  // Determine which version is currently active
  // Original is active when edited_content is null
  // Otherwise match edited_content against entry new_content (last matching entry wins)
  const isActiveVersion = (entry: EditHistoryEntry | null): boolean => {
    if (entry === null) {
      // Original is active when there's no edit overlay
      return node.edited_content == null
    }
    // An edit entry is active if it's the last entry whose new_content matches edited_content
    if (node.edited_content == null) return false
    if (entry.new_content !== node.edited_content) return false
    // Check it's the last entry with this content (in case of duplicate edits)
    const lastMatch = [...entries].reverse().find((e) => e.new_content === node.edited_content)
    return lastMatch?.event_id === entry.event_id
  }

  const handleSetActive = (entry: EditHistoryEntry | null) => {
    // Set the active version: null for original, entry.new_content for an edit
    const content = entry === null ? null : entry.new_content
    editNodeContent(node.node_id, content)
    // Clear version selection so highlights don't persist after applying
    setSelectedEditVersion(node.node_id, null)
  }

  // Build display list: original (v0) + all edit entries
  const allVersions: Array<{
    version: number
    label: string
    isRestore: boolean
    timestamp: string
    entry: EditHistoryEntry | null
  }> = [
    {
      version: 0,
      label: truncate(node.content, 80),
      isRestore: false,
      timestamp: node.created_at,
      entry: null,
    },
    ...entries.map((e, i) => ({
      version: i + 1,
      label: e.new_content ? truncate(e.new_content, 80) : 'Restored to original',
      isRestore: e.new_content === null,
      timestamp: e.timestamp,
      entry: e,
    })),
  ]

  const entryCount = entries.length

  const isSelected = (entry: EditHistoryEntry | null) => {
    if (!selectedEditVersion || selectedEditVersion.nodeId !== node.node_id) return false
    if (entry === null && selectedEditVersion.entry === null) return true
    if (entry && selectedEditVersion.entry) {
      return entry.event_id === selectedEditVersion.entry.event_id
    }
    return false
  }

  return (
    <div className="edit-history">
      <button
        className="edit-history-toggle"
        onClick={handleToggle}
        aria-label={expanded ? 'Collapse edit history' : 'Expand edit history'}
      >
        <span className={`edit-history-chevron ${expanded ? 'expanded' : ''}`}>
          &#x25B6;
        </span>
        Edit history
        <span className="edit-history-count">
          {entryCount > 0 ? `${entryCount} ${entryCount === 1 ? 'version' : 'versions'}` : ''}
        </span>
      </button>

      {expanded && (
        loading ? (
          <div className="edit-history-loading">Loading history...</div>
        ) : (
          <div className="edit-history-list">
            {allVersions.map((v) => {
              const active = isActiveVersion(v.entry)
              return (
                <div
                  key={v.entry?.event_id ?? 'original'}
                  className={`edit-history-entry${isSelected(v.entry) ? ' selected' : ''}${active ? ' active' : ''}`}
                >
                  <button
                    className="edit-history-entry-main"
                    onClick={() => {
                      if (isSelected(v.entry)) {
                        setSelectedEditVersion(node.node_id, null)
                      } else {
                        setSelectedEditVersion(node.node_id, v.entry)
                      }
                    }}
                  >
                    <span className="edit-history-version">v{v.version}</span>
                    <span className={`edit-history-preview${v.isRestore ? ' restore' : ''}`}>
                      {v.label}
                    </span>
                    {active && <span className="edit-history-active-badge">active</span>}
                    <span className="edit-history-time">
                      {formatRelativeTime(v.timestamp)}
                    </span>
                  </button>
                  {!active && (
                    <button
                      className="edit-history-set-active"
                      onClick={(e) => {
                        e.stopPropagation()
                        handleSetActive(v.entry)
                      }}
                      title="Set this version as what the model sees"
                    >
                      Use
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        )
      )}
    </div>
  )
}
