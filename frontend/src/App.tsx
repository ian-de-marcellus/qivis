import { useEffect, useState } from 'react'
import { TreeList } from './components/Library/TreeList.tsx'
import { LinearView } from './components/TreeView/LinearView.tsx'
import { MessageInput } from './components/TreeView/MessageInput.tsx'
import { SystemPromptInput } from './components/TreeView/SystemPromptInput.tsx'
import { TreeSettings } from './components/TreeView/TreeSettings.tsx'
import { useTreeStore } from './store/treeStore.ts'
import './App.css'

function App() {
  const { fetchTrees, currentTree, error, clearError } = useTreeStore()
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  useEffect(() => {
    fetchTrees()
  }, [fetchTrees])

  return (
    <div className="app">
      <aside className={`sidebar ${sidebarCollapsed ? 'collapsed' : ''}`}>
        {!sidebarCollapsed && <TreeList />}
        <div className="sidebar-toggle-bar">
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
