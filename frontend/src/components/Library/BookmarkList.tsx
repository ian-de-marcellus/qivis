import { useState } from 'react'
import type { BookmarkResponse } from '../../api/types.ts'
import { useTreeStore } from '../../store/treeStore.ts'
import './BookmarkList.css'

export function BookmarkList() {
  const {
    bookmarks,
    bookmarksLoading,
    removeBookmark,
    summarizeBookmark,
    navigateToBookmark,
  } = useTreeStore()

  const [searchQuery, setSearchQuery] = useState('')
  const [summarizingIds, setSummarizingIds] = useState<Set<string>>(new Set())
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())

  const filtered = searchQuery.trim()
    ? bookmarks.filter((b) => {
        const q = searchQuery.toLowerCase()
        return (
          b.label.toLowerCase().includes(q) ||
          (b.summary?.toLowerCase().includes(q) ?? false) ||
          (b.notes?.toLowerCase().includes(q) ?? false)
        )
      })
    : bookmarks

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

  const toggleExpanded = (bookmarkId: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(bookmarkId)) {
        next.delete(bookmarkId)
      } else {
        next.add(bookmarkId)
      }
      return next
    })
  }

  if (bookmarksLoading && bookmarks.length === 0) {
    return (
      <div className="bookmark-list">
        <div className="bookmark-list-header">
          <h2>Bookmarks</h2>
        </div>
        <div className="bookmark-empty">Loading...</div>
      </div>
    )
  }

  return (
    <div className="bookmark-list">
      <div className="bookmark-list-header">
        <h2>Bookmarks</h2>
        {bookmarks.length > 0 && (
          <span className="bookmark-count">{bookmarks.length}</span>
        )}
      </div>

      {bookmarks.length > 3 && (
        <div className="bookmark-search">
          <input
            type="text"
            placeholder="Search bookmarks..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
      )}

      <div className="bookmark-items">
        {filtered.map((bookmark) => {
          const isSummarizing = summarizingIds.has(bookmark.bookmark_id)
          const isExpanded = expandedIds.has(bookmark.bookmark_id)

          return (
            <div key={bookmark.bookmark_id} className="bookmark-item">
              <div className="bookmark-item-header">
                <button
                  className="bookmark-label"
                  onClick={() => navigateToBookmark(bookmark)}
                  title="Navigate to bookmarked message"
                >
                  {bookmark.label}
                </button>
                <button
                  className="bookmark-remove"
                  onClick={() => removeBookmark(bookmark.bookmark_id)}
                  aria-label="Remove bookmark"
                  title="Remove bookmark"
                >
                  &times;
                </button>
              </div>

              {bookmark.notes && (
                <div className="bookmark-notes">{bookmark.notes}</div>
              )}

              {bookmark.summary && (
                <div
                  className={`bookmark-summary${isExpanded ? ' expanded' : ''}`}
                  onClick={() => toggleExpanded(bookmark.bookmark_id)}
                  title={isExpanded ? 'Collapse summary' : 'Expand summary'}
                >
                  {bookmark.summary}
                </div>
              )}

              <div className="bookmark-actions">
                <button
                  className="bookmark-summarize"
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

        {bookmarks.length === 0 && (
          <div className="bookmark-empty">
            No bookmarks yet. Click "Mark" on any message to bookmark it.
          </div>
        )}

        {bookmarks.length > 0 && filtered.length === 0 && searchQuery.trim() && (
          <div className="bookmark-empty">No bookmarks match "{searchQuery}"</div>
        )}
      </div>
    </div>
  )
}
