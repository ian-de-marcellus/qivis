import { useCallback, useEffect, useRef, useState } from 'react'
import { CanvasView } from './components/CanvasView/CanvasView.tsx'
import { LibraryView } from './components/Library/LibraryView.tsx'
import { GraphView } from './components/GraphView/GraphView.tsx'
import { ResearchPanel } from './components/Library/ResearchPanel.tsx'
import { SearchPanel } from './components/Library/SearchPanel.tsx'
import { RhizomeList } from './components/Library/RhizomeList.tsx'
import { getRhizomeDefaults } from './components/RhizomeView/contextDiffs.ts'
import { DigressionSidePanel } from './components/RhizomeView/DigressionPanel.tsx'
import { ChatView } from './components/RhizomeView/ChatView.tsx'
import { CompletionView } from './components/RhizomeView/CompletionView.tsx'
import { MessageInput } from './components/RhizomeView/MessageInput.tsx'
import { SystemPromptInput } from './components/RhizomeView/SystemPromptInput.tsx'
import { RhizomeSettings } from './components/RhizomeView/RhizomeSettings.tsx'
import { getActivePath, useRhizomeStore, useRhizomeData, useNavigation, useRightPane } from './store/rhizomeStore.ts'
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
  const { currentRhizome, error } = useRhizomeData()
  const { branchSelections } = useNavigation()
  const { rightPaneMode, canvasOpen, libraryOpen } = useRightPane()
  const searchQuery = useRhizomeStore(s => s.searchQuery)
  const fetchRhizomes = useRhizomeStore(s => s.fetchRhizomes)
  const clearError = useRhizomeStore(s => s.clearError)
  const setCanvasOpen = useRhizomeStore(s => s.setCanvasOpen)
  const setLibraryOpen = useRhizomeStore(s => s.setLibraryOpen)

  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [theme, setTheme] = useState<ThemeMode>(getInitialTheme)
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
    fetchRhizomes()
  }, [fetchRhizomes])

  // Cmd+Shift+L toggles the library view
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === 'l') {
        e.preventDefault()
        setLibraryOpen(!libraryOpen)
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [libraryOpen, setLibraryOpen])

  return (
    <div className="app">
      <aside className={`sidebar ${sidebarCollapsed ? 'collapsed' : ''}`}>
        {!sidebarCollapsed && <SearchPanel />}
        {!sidebarCollapsed && !searchQuery && <RhizomeList />}
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

        {currentRhizome ? (
          rightPaneMode != null ? (
            <div className="split-layout">
              <div className="linear-pane">
                <RhizomeSettings />
                {(currentRhizome.metadata?.generation_mode as string) !== 'completion' && <SystemPromptInput />}
                {(currentRhizome.metadata?.generation_mode as string) === 'completion'
                  ? <CompletionView />
                  : <ChatView />
                }
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
                {rightPaneMode === 'graph' && <GraphView />}
                {rightPaneMode === 'digressions' && <DigressionSidePanel />}
                {rightPaneMode === 'research' && <ResearchPanel />}
              </div>
            </div>
          ) : (
            <>
              <RhizomeSettings />
              {(currentRhizome.metadata?.generation_mode as string) !== 'completion' && <SystemPromptInput />}
              {(currentRhizome.metadata?.generation_mode as string) === 'completion'
                ? <CompletionView />
                : <ChatView />
              }
              <MessageInput />
            </>
          )
        ) : (
          <div className="empty-state">
            <h1>Qivis</h1>
            <p>Select a rhizome or create a new one to begin.</p>
          </div>
        )}

        {canvasOpen && currentRhizome && (
          <CanvasView
            rhizomeId={currentRhizome.rhizome_id}
            pathNodes={getActivePath(currentRhizome.nodes, branchSelections)}
            rhizomeDefaults={getRhizomeDefaults(currentRhizome)}
            onDismiss={() => setCanvasOpen(false)}
          />
        )}

        {libraryOpen && (
          <LibraryView onDismiss={() => setLibraryOpen(false)} />
        )}
      </main>
    </div>
  )
}

export default App
