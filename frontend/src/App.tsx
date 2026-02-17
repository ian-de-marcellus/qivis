import { useCallback, useEffect, useRef, useState } from 'react'
import { CanvasView } from './components/CanvasView/CanvasView.tsx'
import { GraphView } from './components/GraphView/GraphView.tsx'
import { BookmarkList } from './components/Library/BookmarkList.tsx'
import { TreeList } from './components/Library/TreeList.tsx'
import { getTreeDefaults } from './components/TreeView/contextDiffs.ts'
import { LinearView } from './components/TreeView/LinearView.tsx'
import { MessageInput } from './components/TreeView/MessageInput.tsx'
import { SystemPromptInput } from './components/TreeView/SystemPromptInput.tsx'
import { TreeSettings } from './components/TreeView/TreeSettings.tsx'
import { getActivePath, useTreeStore } from './store/treeStore.ts'
import './App.css'

type ThemeMode = 'system' | 'light' | 'dark'

const THEME_KEY = 'qivis-theme'
const THEME_LABELS: Record<ThemeMode, string> = {
  system: '\u25D0',  // ◐ half circle
  light: '\u263C',   // ☼ sun
  dark: '\u263E',    // ☾ moon
}
const THEME_CYCLE: ThemeMode[] = ['system', 'light', 'dark']

function getInitialTheme(): ThemeMode {
  const stored = localStorage.getItem(THEME_KEY)
  if (stored === 'light' || stored === 'dark') return stored
  return 'system'
}

function applyTheme(mode: ThemeMode) {
  if (mode === 'light' || mode === 'dark') {
    document.documentElement.dataset.theme = mode
  } else {
    delete document.documentElement.dataset.theme
  }
}

function App() {
  const { fetchTrees, currentTree, error, clearError, canvasOpen, setCanvasOpen, branchSelections } = useTreeStore()
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [theme, setTheme] = useState<ThemeMode>(getInitialTheme)
  const [graphOpen, setGraphOpen] = useState(false)
  const [graphPaneWidth, setGraphPaneWidth] = useState(0) // 0 = use default %
  const isResizing = useRef(false)
  const mainRef = useRef<HTMLElement>(null)

  const startResize = useCallback((e: React.PointerEvent) => {
    e.preventDefault()
    isResizing.current = true
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'

    const onMove = (me: PointerEvent) => {
      if (!isResizing.current || !mainRef.current) return
      const mainRect = mainRef.current.getBoundingClientRect()
      // Graph is on the right — width = distance from right edge of main to cursor
      const width = mainRect.right - me.clientX
      const minW = 200
      const maxW = mainRect.width * 0.6
      setGraphPaneWidth(Math.min(maxW, Math.max(minW, width)))
    }

    const onUp = () => {
      isResizing.current = false
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      document.removeEventListener('pointermove', onMove)
      document.removeEventListener('pointerup', onUp)
    }

    document.addEventListener('pointermove', onMove)
    document.addEventListener('pointerup', onUp)
  }, [])

  // Apply theme on mount and changes
  useEffect(() => {
    applyTheme(theme)
    localStorage.setItem(THEME_KEY, theme)
  }, [theme])

  const cycleTheme = () => {
    const idx = THEME_CYCLE.indexOf(theme)
    setTheme(THEME_CYCLE[(idx + 1) % THEME_CYCLE.length])
  }

  useEffect(() => {
    fetchTrees()
  }, [fetchTrees])

  return (
    <div className="app">
      <aside className={`sidebar ${sidebarCollapsed ? 'collapsed' : ''}`}>
        {!sidebarCollapsed && <TreeList />}
        {!sidebarCollapsed && currentTree && <BookmarkList />}
        <div className="sidebar-toggle-bar">
          <button
            className="theme-toggle"
            onClick={cycleTheme}
            aria-label={`Theme: ${theme}`}
            title={`Theme: ${theme}`}
          >
            {THEME_LABELS[theme]}
          </button>
          <button
            className="sidebar-toggle"
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            aria-label={sidebarCollapsed ? 'Show sidebar' : 'Hide sidebar'}
          >
            <span className={`sidebar-toggle-icon ${sidebarCollapsed ? 'collapsed' : ''}`} />
          </button>
        </div>
      </aside>

      <main className="main" ref={mainRef}>
        {error && (
          <div className="error-banner">
            <span>{error}</span>
            <button onClick={clearError}>Dismiss</button>
          </div>
        )}

        {currentTree ? (
          graphOpen ? (
            <div className="split-layout">
              <div className="linear-pane">
                <TreeSettings
                  graphOpen={graphOpen}
                  onToggleGraph={() => setGraphOpen(false)}
                />
                <SystemPromptInput />
                <LinearView />
                <MessageInput />
              </div>
              <div
                className="split-divider"
                onPointerDown={startResize}
              />
              <div
                className="graph-pane"
                style={graphPaneWidth > 0 ? { width: graphPaneWidth } : undefined}
              >
                <GraphView />
              </div>
            </div>
          ) : (
            <>
              <TreeSettings
                graphOpen={graphOpen}
                onToggleGraph={() => setGraphOpen(true)}
              />
              <SystemPromptInput />
              <LinearView />
              <MessageInput />
            </>
          )
        ) : (
          <div className="empty-state">
            <h1>Qivis</h1>
            <p>Select a tree or create a new one to begin.</p>
          </div>
        )}

        {canvasOpen && currentTree && (
          <CanvasView
            treeId={currentTree.tree_id}
            pathNodes={getActivePath(currentTree.nodes, branchSelections)}
            treeDefaults={getTreeDefaults(currentTree)}
            onDismiss={() => setCanvasOpen(false)}
          />
        )}
      </main>
    </div>
  )
}

export default App
