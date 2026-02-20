import { useCallback, useEffect, useRef } from 'react'
import { useTreeStore } from '../../store/treeStore.ts'
import * as api from '../../api/client.ts'
import type { SearchResultItem } from '../../api/types.ts'
import './SearchPanel.css'

function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  return new Date(iso).toLocaleDateString()
}

function renderSnippet(snippet: string) {
  const parts = snippet.split(/\[\[mark\]\](.*?)\[\[\/mark\]\]/g)
  return parts.map((part, i) =>
    i % 2 === 1 ? <mark key={i}>{part}</mark> : part
  )
}

function SearchResult({ result, onClick }: {
  result: SearchResultItem
  onClick: () => void
}) {
  return (
    <button className="search-result" onClick={onClick}>
      <div className="search-result-tree">
        {result.tree_title || 'Untitled'}
      </div>
      <div className="search-result-snippet">
        <span className={`search-result-role ${result.role}`}>
          {result.role}
        </span>
        {renderSnippet(result.snippet)}
      </div>
      <div className="search-result-meta">
        {result.model && <>{result.model} · </>}
        {formatRelativeTime(result.created_at)}
      </div>
    </button>
  )
}

export function SearchPanel() {
  const searchQuery = useTreeStore(s => s.searchQuery)
  const searchResults = useTreeStore(s => s.searchResults)
  const searchLoading = useTreeStore(s => s.searchLoading)
  const setSearchQuery = useTreeStore(s => s.setSearchQuery)
  const clearSearch = useTreeStore(s => s.clearSearch)
  const navigateToSearchResult = useTreeStore(s => s.navigateToSearchResult)
  const inputRef = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const executeSearch = useCallback(async (query: string) => {
    if (!query.trim()) return
    useTreeStore.setState({ searchLoading: true })
    try {
      const response = await api.searchNodes({ q: query, limit: 50 })
      useTreeStore.setState({
        searchResults: response.results,
        searchLoading: false,
      })
    } catch {
      useTreeStore.setState({ searchResults: [], searchLoading: false })
    }
  }, [])

  const handleChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value
    setSearchQuery(value)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (value.trim()) {
      debounceRef.current = setTimeout(() => executeSearch(value), 300)
    }
  }, [setSearchQuery, executeSearch])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      clearSearch()
      inputRef.current?.blur()
    }
  }, [clearSearch])

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [])

  const hasQuery = searchQuery.trim().length > 0

  return (
    <div className={`search-panel${hasQuery ? ' has-results' : ''}`}>
      <div className="search-input-wrap">
        <input
          ref={inputRef}
          type="text"
          placeholder="Search all trees..."
          value={searchQuery}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
        />
        {hasQuery && (
          <button className="search-clear" onClick={clearSearch} aria-label="Clear search">
            ×
          </button>
        )}
      </div>

      {hasQuery && (
        <div className="search-results">
          {searchLoading ? (
            <div className="search-loading">Searching...</div>
          ) : searchResults.length > 0 ? (
            searchResults.map(result => (
              <SearchResult
                key={result.node_id}
                result={result}
                onClick={() => navigateToSearchResult(result.tree_id, result.node_id)}
              />
            ))
          ) : (
            <div className="search-empty">No results for "{searchQuery}"</div>
          )}
        </div>
      )}
    </div>
  )
}
