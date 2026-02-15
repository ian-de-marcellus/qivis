import { useEffect } from 'react'
import { TreeList } from './components/Library/TreeList.tsx'
import { LinearView } from './components/TreeView/LinearView.tsx'
import { MessageInput } from './components/TreeView/MessageInput.tsx'
import { SystemPromptInput } from './components/TreeView/SystemPromptInput.tsx'
import { useTreeStore } from './store/treeStore.ts'

function App() {
  const { fetchTrees, currentTree, error, clearError } = useTreeStore()

  useEffect(() => {
    fetchTrees()
  }, [fetchTrees])

  return (
    <div className="app">
      <aside className="sidebar">
        <TreeList />
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
            <SystemPromptInput />
            <LinearView />
            <MessageInput />
          </>
        ) : (
          <div className="empty-state">
            <h1>Qivis</h1>
            <p>Select a tree or create a new one to start.</p>
          </div>
        )}
      </main>
    </div>
  )
}

export default App
