import { useEffect, useState } from 'react'
import { TreeList } from './components/Library/TreeList.tsx'
import { LinearView } from './components/TreeView/LinearView.tsx'
import { MessageInput } from './components/TreeView/MessageInput.tsx'
import { SystemPromptInput } from './components/TreeView/SystemPromptInput.tsx'
import { TreeSettings } from './components/TreeView/TreeSettings.tsx'
import { useTreeStore } from './store/treeStore.ts'
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
  const { fetchTrees, currentTree, error, clearError } = useTreeStore()
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [theme, setTheme] = useState<ThemeMode>(getInitialTheme)

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

      <main className="main">
        {error && (
          <div className="error-banner">
            <span>{error}</span>
            <button onClick={clearError}>Dismiss</button>
          </div>
        )}

        {currentTree ? (
          <>
            <TreeSettings />
            <SystemPromptInput />
            <LinearView />
            <MessageInput />
          </>
        ) : (
          <div className="empty-state">
            <h1>Qivis</h1>
            <p>Select a tree or create a new one to begin.</p>
          </div>
        )}
      </main>
    </div>
  )
}

export default App
