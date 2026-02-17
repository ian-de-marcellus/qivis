import { useEffect, useState } from 'react'
import type { NodeResponse } from '../../api/types.ts'
import { useTreeStore } from '../../store/treeStore.ts'
import './AnnotationPanel.css'

interface AnnotationPanelProps {
  node: NodeResponse
}

export function AnnotationPanel({ node }: AnnotationPanelProps) {
  const [customTag, setCustomTag] = useState('')
  const [showNotesFor, setShowNotesFor] = useState<string | null>(null)
  const [notesValue, setNotesValue] = useState('')

  const nodeAnnotations = useTreeStore((s) => s.nodeAnnotations[node.node_id])
  const taxonomy = useTreeStore((s) => s.taxonomy)
  const addAnnotation = useTreeStore((s) => s.addAnnotation)
  const removeAnnotation = useTreeStore((s) => s.removeAnnotation)
  const fetchNodeAnnotations = useTreeStore((s) => s.fetchNodeAnnotations)
  const fetchTaxonomy = useTreeStore((s) => s.fetchTaxonomy)

  // Fetch on mount if not cached
  useEffect(() => {
    if (nodeAnnotations == null) {
      fetchNodeAnnotations(node.node_id)
    }
  }, [node.node_id, nodeAnnotations, fetchNodeAnnotations])

  useEffect(() => {
    if (taxonomy == null) {
      fetchTaxonomy()
    }
  }, [taxonomy, fetchTaxonomy])

  const annotations = nodeAnnotations ?? []
  const appliedTags = new Set(annotations.map((a) => a.tag))

  // Merge base + used tags for the quick-tag row, preserving order
  const allTags: string[] = []
  if (taxonomy) {
    for (const tag of taxonomy.base_tags) {
      allTags.push(tag)
    }
    for (const tag of taxonomy.used_tags) {
      if (!allTags.includes(tag)) {
        allTags.push(tag)
      }
    }
  }

  const handleQuickTag = async (tag: string) => {
    if (appliedTags.has(tag)) {
      // Remove the first annotation with this tag
      const existing = annotations.find((a) => a.tag === tag)
      if (existing) {
        await removeAnnotation(node.node_id, existing.annotation_id)
      }
    } else {
      await addAnnotation(node.node_id, tag)
    }
  }

  const handleCustomTag = async () => {
    const tag = customTag.trim().toLowerCase().replace(/\s+/g, '-')
    if (!tag) return
    await addAnnotation(node.node_id, tag)
    setCustomTag('')
  }

  const handleAddNotes = async (annotationId: string) => {
    const existing = annotations.find((a) => a.annotation_id === annotationId)
    if (!existing) return
    // Remove and re-add with notes
    await removeAnnotation(node.node_id, annotationId)
    await addAnnotation(node.node_id, existing.tag, existing.value ?? undefined, notesValue || undefined)
    setShowNotesFor(null)
    setNotesValue('')
  }

  return (
    <div className="annotation-panel">
      {/* Quick-tag chips */}
      {allTags.length > 0 && (
        <div className="annotation-tags">
          {allTags.map((tag) => (
            <button
              key={tag}
              className={`annotation-chip${appliedTags.has(tag) ? ' active' : ''}`}
              onClick={() => handleQuickTag(tag)}
            >
              {tag}
            </button>
          ))}
        </div>
      )}

      {/* Custom tag input */}
      <div className="annotation-custom">
        <input
          type="text"
          className="annotation-input"
          value={customTag}
          onChange={(e) => setCustomTag(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              handleCustomTag()
            }
          }}
          placeholder="custom tag..."
        />
      </div>

      {/* Existing annotations list */}
      {annotations.length > 0 && (
        <div className="annotation-list">
          {annotations.map((ann) => (
            <div key={ann.annotation_id} className="annotation-item">
              <span className="annotation-item-tag">{ann.tag}</span>
              {ann.notes && (
                <span className="annotation-item-notes">{ann.notes}</span>
              )}
              {!ann.notes && showNotesFor !== ann.annotation_id && (
                <button
                  className="annotation-add-notes"
                  onClick={() => {
                    setShowNotesFor(ann.annotation_id)
                    setNotesValue('')
                  }}
                >
                  + note
                </button>
              )}
              {showNotesFor === ann.annotation_id && (
                <div className="annotation-notes-form">
                  <input
                    type="text"
                    className="annotation-notes-input"
                    value={notesValue}
                    onChange={(e) => setNotesValue(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        handleAddNotes(ann.annotation_id)
                      }
                      if (e.key === 'Escape') {
                        setShowNotesFor(null)
                      }
                    }}
                    placeholder="Add a note..."
                    autoFocus
                  />
                </div>
              )}
              <button
                className="annotation-remove"
                onClick={() => removeAnnotation(node.node_id, ann.annotation_id)}
                aria-label={`Remove ${ann.tag} annotation`}
              >
                &times;
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
