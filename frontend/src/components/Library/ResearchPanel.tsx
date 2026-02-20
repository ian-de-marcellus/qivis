import { useState } from 'react'
import type { BookmarkResponse } from '../../api/types.ts'
import { useTreeStore, useResearchMetadata } from '../../store/treeStore.ts'
import './ResearchPanel.css'

export function ResearchPanel() {
  const {
    bookmarks, bookmarksLoading,
    treeNotes, treeAnnotations,
    researchPaneTab,
  } = useResearchMetadata()

  const navigateToNode = useTreeStore(s => s.navigateToNode)
  const removeBookmark = useTreeStore(s => s.removeBookmark)
  const summarizeBookmark = useTreeStore(s => s.summarizeBookmark)
  const navigateToBookmark = useTreeStore(s => s.navigateToBookmark)
  const removeNote = useTreeStore(s => s.removeNote)
  const setResearchPaneTab = useTreeStore(s => s.setResearchPaneTab)
  const currentTree = useTreeStore(s => s.currentTree)

  const [summarizingIds, setSummarizingIds] = useState<Set<string>>(new Set())
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())

  const totalCount = bookmarks.length + treeAnnotations.length + treeNotes.length

  const handleSummarize = async (bookmark: BookmarkResponse) => {
    setSummarizingIds((prev) => new Set([...prev, bookmark.bookmark_id]))
    try {
      await summarizeBookmark(bookmark.bookmark_id)
    } finally {
      setSummarizingIds((prev) => {
        const next = new Set(prev)
        next.delete(bookmark.bookmark_id)
        return next
      })
    }
  }

  const toggleExpanded = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // Build a node content preview map for notes/annotations
  const nodePreviewMap = new Map<string, string>()
  if (currentTree) {
    for (const n of currentTree.nodes) {
      const text = n.edited_content ?? n.content
      nodePreviewMap.set(n.node_id, text.length > 80 ? text.slice(0, 80) + '...' : text)
    }
  }

  return (
    <div className="research-panel">
      <div className="research-panel-header">
        <h2>Research</h2>
        {totalCount > 0 && (
          <span className="research-count">{totalCount}</span>
        )}
      </div>

      <div className="research-tabs">
        <button
          className={`research-tab${researchPaneTab === 'bookmarks' ? ' active' : ''}`}
          onClick={() => setResearchPaneTab('bookmarks')}
        >
          Bookmarks{bookmarks.length > 0 && <span className="tab-count">{bookmarks.length}</span>}
        </button>
        <button
          className={`research-tab${researchPaneTab === 'tags' ? ' active' : ''}`}
          onClick={() => setResearchPaneTab('tags')}
        >
          Tags{treeAnnotations.length > 0 && <span className="tab-count">{treeAnnotations.length}</span>}
        </button>
        <button
          className={`research-tab${researchPaneTab === 'notes' ? ' active' : ''}`}
          onClick={() => setResearchPaneTab('notes')}
        >
          Notes{treeNotes.length > 0 && <span className="tab-count">{treeNotes.length}</span>}
        </button>
      </div>

      <div className="research-content">
        {/* Bookmarks tab */}
        {researchPaneTab === 'bookmarks' && (
          <div className="research-items">
            {bookmarksLoading && bookmarks.length === 0 && (
              <div className="research-empty">Loading...</div>
            )}

            {bookmarks.map((bookmark) => {
              const isSummarizing = summarizingIds.has(bookmark.bookmark_id)
              const isExpanded = expandedIds.has(bookmark.bookmark_id)

              return (
                <div key={bookmark.bookmark_id} className="research-item">
                  <div className="research-item-header">
                    <button
                      className="research-item-label"
                      onClick={() => navigateToBookmark(bookmark)}
                      title="Navigate to bookmarked message"
                    >
                      {bookmark.label}
                    </button>
                    <button
                      className="research-item-remove"
                      onClick={() => removeBookmark(bookmark.bookmark_id)}
                      aria-label="Remove bookmark"
                    >
                      &times;
                    </button>
                  </div>

                  {bookmark.notes && (
                    <div className="research-item-notes">{bookmark.notes}</div>
                  )}

                  {bookmark.summary && (
                    <div
                      className={`research-item-summary${isExpanded ? ' expanded' : ''}`}
                      onClick={() => toggleExpanded(bookmark.bookmark_id)}
                    >
                      {bookmark.summary}
                    </div>
                  )}

                  <div className="research-item-actions">
                    <button
                      className="research-summarize-btn"
                      onClick={() => handleSummarize(bookmark)}
                      disabled={isSummarizing}
                    >
                      {isSummarizing
                        ? 'Summarizing...'
                        : bookmark.summary
                          ? 'Resummarize'
                          : 'Summarize'}
                    </button>
                  </div>
                </div>
              )
            })}

            {bookmarks.length === 0 && !bookmarksLoading && (
              <div className="research-empty">
                No bookmarks yet. Click "Mark" on any message.
              </div>
            )}
          </div>
        )}

        {/* Tags tab */}
        {researchPaneTab === 'tags' && (
          <div className="research-items">
            {treeAnnotations.map((ann) => (
              <div key={ann.annotation_id} className="research-item clickable"
                onClick={() => navigateToNode(ann.node_id)}
              >
                <div className="research-item-header">
                  <span className="research-tag-chip">{ann.tag}</span>
                  <span className="research-item-time">{formatShortTime(ann.created_at)}</span>
                </div>
                {ann.notes && (
                  <div className="research-item-notes">{ann.notes}</div>
                )}
                <div className="research-item-preview">
                  {nodePreviewMap.get(ann.node_id) ?? ''}
                </div>
              </div>
            ))}

            {treeAnnotations.length === 0 && (
              <div className="research-empty">
                No tags yet. Click "Tag" on any message.
              </div>
            )}
          </div>
        )}

        {/* Notes tab */}
        {researchPaneTab === 'notes' && (
          <div className="research-items">
            {treeNotes.map((note) => (
              <div key={note.note_id} className="research-item">
                <div className="research-item-header">
                  <button
                    className="research-item-label"
                    onClick={() => navigateToNode(note.node_id)}
                    title="Navigate to message"
                  >
                    {note.content.length > 60 ? note.content.slice(0, 60) + '...' : note.content}
                  </button>
                  <button
                    className="research-item-remove"
                    onClick={() => removeNote(note.node_id, note.note_id)}
                    aria-label="Remove note"
                  >
                    &times;
                  </button>
                </div>
                <div className="research-item-preview">
                  {nodePreviewMap.get(note.node_id) ?? ''}
                </div>
                <div className="research-item-time">{formatShortTime(note.created_at)}</div>
              </div>
            ))}

            {treeNotes.length === 0 && (
              <div className="research-empty">
                No notes yet. Click "Note" on any message.
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function formatShortTime(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  } catch {
    return ''
  }
}
