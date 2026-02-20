import { useEffect, useState } from 'react'
import type { NodeResponse } from '../../api/types.ts'
import { useTreeStore } from '../../store/treeStore.ts'
import './NotePanel.css'

interface NotePanelProps {
  node: NodeResponse
}

export function NotePanel({ node }: NotePanelProps) {
  const [draft, setDraft] = useState('')

  const nodeNotes = useTreeStore((s) => s.nodeNotes[node.node_id])
  const addNote = useTreeStore((s) => s.addNote)
  const removeNote = useTreeStore((s) => s.removeNote)
  const fetchNodeNotes = useTreeStore((s) => s.fetchNodeNotes)

  useEffect(() => {
    if (nodeNotes == null) {
      fetchNodeNotes(node.node_id)
    }
  }, [node.node_id, nodeNotes, fetchNodeNotes])

  const notes = nodeNotes ?? []

  const handleSubmit = async () => {
    const content = draft.trim()
    if (!content) return
    await addNote(node.node_id, content)
    setDraft('')
  }

  return (
    <div className="note-panel">
      <div className="note-input-row">
        <textarea
          className="note-textarea"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
              e.preventDefault()
              handleSubmit()
            }
          }}
          placeholder="Add a note..."
          rows={2}
        />
        <button
          className="note-submit"
          onClick={handleSubmit}
          disabled={!draft.trim()}
        >
          Add
        </button>
      </div>

      {notes.length > 0 && (
        <div className="note-list">
          {notes.map((note) => (
            <div key={note.note_id} className="note-item">
              <div className="note-content">{note.content}</div>
              <div className="note-item-meta">
                {formatNoteTime(note.created_at)}
                <button
                  className="note-remove"
                  onClick={() => removeNote(node.node_id, note.note_id)}
                  aria-label="Remove note"
                >
                  &times;
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function formatNoteTime(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
      + ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso
  }
}
