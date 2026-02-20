import { useState } from 'react'
import type { DigressionGroupResponse, NodeResponse } from '../../api/types.ts'
import { getActivePath, useTreeStore } from '../../store/treeStore.ts'
import './DigressionPanel.css'

interface DigressionPanelProps {
  groups: DigressionGroupResponse[]
  path: NodeResponse[]
  onDismiss: () => void
  onStartSelection: () => void
}

export function DigressionPanel({ groups, path, onDismiss, onStartSelection }: DigressionPanelProps) {
  const { currentTree, toggleDigressionGroup, deleteDigressionGroup, anchorGroup } = useTreeStore()
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)

  const pathNodeIds = new Set(path.map((n) => n.node_id))

  return (
    <div className="digression-panel">
      <div className="digression-panel-header">
        <span className="digression-panel-title">Digression Groups</span>
        <div className="digression-panel-actions">
          <button className="digression-new-btn" onClick={onStartSelection}>
            New Group
          </button>
          <button className="digression-close-btn" onClick={onDismiss}>
            Close
          </button>
        </div>
      </div>

      {groups.length === 0 ? (
        <div className="digression-empty">
          No digression groups yet. Create one to toggle contiguous messages in or out of context.
        </div>
      ) : (
        <div className="digression-list">
          {groups.map((group) => {
            const allOnPath = group.node_ids.every((nid) => pathNodeIds.has(nid))
            const allAnchored = currentTree != null && group.node_ids.every((nid) => {
              const node = currentTree.nodes.find((n) => n.node_id === nid)
              return node?.is_anchored ?? false
            })
            return (
              <div
                key={group.group_id}
                className={`digression-item${!allOnPath ? ' off-path' : ''}`}
              >
                <div className="digression-item-main">
                  <label className="digression-toggle">
                    <input
                      type="checkbox"
                      checked={group.included}
                      onChange={() => toggleDigressionGroup(group.group_id, !group.included)}
                    />
                    <span className="digression-toggle-track" />
                  </label>
                  <span className="digression-item-label">{group.label}</span>
                  <span className="digression-item-count">
                    {group.node_ids.length} msg{group.node_ids.length !== 1 ? 's' : ''}
                  </span>
                  {!allOnPath && (
                    <span className="digression-item-offpath">off path</span>
                  )}
                </div>
                <div className="digression-item-actions">
                  <button
                    className={`digression-anchor-btn${allAnchored ? ' anchored' : ''}`}
                    onClick={() => anchorGroup(group.group_id)}
                    title={allAnchored ? 'Unanchor all nodes in group' : 'Anchor all nodes in group'}
                  >
                    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round">
                      <circle cx="8" cy="3.5" r="2" />
                      <line x1="8" y1="5.5" x2="8" y2="13" />
                      <line x1="4.5" y1="10" x2="11.5" y2="10" />
                    </svg>
                  </button>
                  {confirmDelete === group.group_id ? (
                    <>
                      <button
                        className="digression-confirm-delete"
                        onClick={() => {
                          deleteDigressionGroup(group.group_id)
                          setConfirmDelete(null)
                        }}
                      >
                        Confirm
                      </button>
                      <button
                        className="digression-cancel-delete"
                        onClick={() => setConfirmDelete(null)}
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <button
                      className="digression-delete-btn"
                      onClick={() => setConfirmDelete(group.group_id)}
                    >
                      Delete
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

interface DigressionCreatorProps {
  selectedNodeIds: string[]
  onToggleNode: (nodeId: string) => void
  onCancel: () => void
  onCreate: (label: string) => void
}

export function DigressionCreator({ selectedNodeIds, onToggleNode: _onToggleNode, onCancel, onCreate }: DigressionCreatorProps) {
  const [label, setLabel] = useState('')

  return (
    <div className="digression-creator">
      <div className="digression-creator-header">
        <span className="digression-creator-title">Creating digression group</span>
        <span className="digression-creator-hint">
          Click messages to select them ({selectedNodeIds.length} selected)
        </span>
      </div>
      <div className="digression-creator-form">
        <input
          className="digression-creator-input"
          type="text"
          placeholder="Group label..."
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && label.trim() && selectedNodeIds.length >= 2) {
              onCreate(label.trim())
            } else if (e.key === 'Escape') {
              onCancel()
            }
          }}
          autoFocus
        />
        <button
          className="digression-creator-submit"
          onClick={() => onCreate(label.trim())}
          disabled={!label.trim() || selectedNodeIds.length < 2}
        >
          Create
        </button>
        <button className="digression-creator-cancel" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  )
}

/**
 * Side panel version — reads directly from the store.
 * Designed to live in the right pane alongside (or instead of) the graph view.
 */
export function DigressionSidePanel() {
  const {
    currentTree,
    digressionGroups,
    branchSelections,
    toggleDigressionGroup,
    deleteDigressionGroup,
    anchorGroup,
    setDigressionPanelOpen,
    setGroupSelectionMode,
  } = useTreeStore()

  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)

  const nodes = currentTree?.nodes ?? []
  const path = getActivePath(nodes, branchSelections)
  const pathNodeIds = new Set(path.map((n) => n.node_id))

  return (
    <div className="digression-side-panel">
      <div className="digression-side-header">
        <span className="digression-panel-title">Digression Groups</span>
        <div className="digression-panel-actions">
          <button
            className="digression-new-btn"
            onClick={() => {
              setGroupSelectionMode(true)
              setDigressionPanelOpen(false)
            }}
          >
            New Group
          </button>
          <button
            className="digression-close-btn"
            onClick={() => setDigressionPanelOpen(false)}
          >
            Close
          </button>
        </div>
      </div>

      <div className="digression-side-body">
        {digressionGroups.length === 0 ? (
          <div className="digression-empty">
            No digression groups yet. Select contiguous messages in the conversation, then create a group to toggle them in or out of context.
          </div>
        ) : (
          <div className="digression-list">
            {digressionGroups.map((group) => {
              const allOnPath = group.node_ids.every((nid) => pathNodeIds.has(nid))
              const allAnchored = currentTree != null && group.node_ids.every((nid) => {
                const node = currentTree.nodes.find((n) => n.node_id === nid)
                return node?.is_anchored ?? false
              })
              return (
                <div
                  key={group.group_id}
                  className={`digression-item${!allOnPath ? ' off-path' : ''}`}
                >
                  <div className="digression-item-main">
                    <label className="digression-toggle">
                      <input
                        type="checkbox"
                        checked={group.included}
                        onChange={() => toggleDigressionGroup(group.group_id, !group.included)}
                      />
                      <span className="digression-toggle-track" />
                    </label>
                    <span className="digression-item-label">{group.label}</span>
                    <span className="digression-item-count">
                      {group.node_ids.length} msg{group.node_ids.length !== 1 ? 's' : ''}
                    </span>
                    {!allOnPath && (
                      <span className="digression-item-offpath">off path</span>
                    )}
                  </div>
                  <div className="digression-item-actions">
                    <button
                      className={`digression-anchor-btn${allAnchored ? ' anchored' : ''}`}
                      onClick={() => anchorGroup(group.group_id)}
                      title={allAnchored ? 'Unanchor all nodes in group' : 'Anchor all nodes in group'}
                    >
                      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round">
                        <circle cx="8" cy="3.5" r="2" />
                        <line x1="8" y1="5.5" x2="8" y2="13" />
                        <line x1="4.5" y1="10" x2="11.5" y2="10" />
                      </svg>
                    </button>
                    {confirmDelete === group.group_id ? (
                      <>
                        <button
                          className="digression-confirm-delete"
                          onClick={() => {
                            deleteDigressionGroup(group.group_id)
                            setConfirmDelete(null)
                          }}
                        >
                          Confirm
                        </button>
                        <button
                          className="digression-cancel-delete"
                          onClick={() => setConfirmDelete(null)}
                        >
                          Cancel
                        </button>
                      </>
                    ) : (
                      <button
                        className="digression-delete-btn"
                        onClick={() => setConfirmDelete(group.group_id)}
                      >
                        Delete
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      <div className="digression-side-hint">
        Click "New Group" to select contiguous messages in the conversation, then name the group. Toggle groups on/off to include or exclude them from the model's context.
      </div>
    </div>
  )
}
