import { useState } from 'react'
import type { CreateSummaryRequest, SummaryResponse } from '../../api/types.ts'
import { useTreeStore } from '../../store/treeStore.ts'
import './SummarizePanel.css'

type Scope = 'branch' | 'subtree'
type SummaryType = 'concise' | 'detailed' | 'key_points' | 'custom'

interface SummarizePanelProps {
  nodeId: string
  onClose: () => void
}

export function SummarizePanel({ nodeId, onClose }: SummarizePanelProps) {
  const [scope, setScope] = useState<Scope>('branch')
  const [summaryType, setSummaryType] = useState<SummaryType>('concise')
  const [customPrompt, setCustomPrompt] = useState('')
  const [generating, setGenerating] = useState(false)
  const [result, setResult] = useState<SummaryResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const generateSummary = useTreeStore(s => s.generateSummary)

  const handleGenerate = async () => {
    setGenerating(true)
    setError(null)
    try {
      const req: CreateSummaryRequest = {
        scope,
        summary_type: summaryType,
      }
      if (summaryType === 'custom' && customPrompt.trim()) {
        req.custom_prompt = customPrompt.trim()
      }
      const summary = await generateSummary(nodeId, req)
      if (summary) {
        setResult(summary)
      } else {
        setError('Failed to generate summary')
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div className="summarize-panel">
      <div className="summarize-panel-header">
        <span className="summarize-panel-title">Summarize</span>
        <button className="summarize-panel-close" onClick={onClose}>
          Close
        </button>
      </div>

      {result ? (
        <div className="summarize-result">
          <div className="summarize-result-badges">
            <span className="summarize-badge scope">{result.scope}</span>
            <span className="summarize-badge type">{result.summary_type}</span>
            <span className="summarize-result-model">{result.model}</span>
          </div>
          <div className="summarize-result-text">{result.summary}</div>
          <div className="summarize-result-meta">
            {result.node_ids.length} nodes summarized
          </div>
          <div className="summarize-result-actions">
            <button
              className="summarize-another"
              onClick={() => setResult(null)}
            >
              Another
            </button>
            <button className="summarize-done" onClick={onClose}>
              Done
            </button>
          </div>
        </div>
      ) : (
        <div className="summarize-panel-body">
          <div className="summarize-option-group">
            <label className="summarize-option-label">Scope</label>
            <div className="summarize-option-buttons">
              <button
                className={`summarize-option${scope === 'branch' ? ' active' : ''}`}
                onClick={() => setScope('branch')}
              >
                Branch
              </button>
              <button
                className={`summarize-option${scope === 'subtree' ? ' active' : ''}`}
                onClick={() => setScope('subtree')}
              >
                Subtree
              </button>
            </div>
          </div>

          <div className="summarize-option-group">
            <label className="summarize-option-label">Type</label>
            <div className="summarize-option-buttons">
              <button
                className={`summarize-option${summaryType === 'concise' ? ' active' : ''}`}
                onClick={() => setSummaryType('concise')}
              >
                Concise
              </button>
              <button
                className={`summarize-option${summaryType === 'detailed' ? ' active' : ''}`}
                onClick={() => setSummaryType('detailed')}
              >
                Detailed
              </button>
              <button
                className={`summarize-option${summaryType === 'key_points' ? ' active' : ''}`}
                onClick={() => setSummaryType('key_points')}
              >
                Key Points
              </button>
              <button
                className={`summarize-option${summaryType === 'custom' ? ' active' : ''}`}
                onClick={() => setSummaryType('custom')}
              >
                Custom
              </button>
            </div>
          </div>

          {summaryType === 'custom' && (
            <textarea
              className="summarize-custom-prompt"
              value={customPrompt}
              onChange={(e) => setCustomPrompt(e.target.value)}
              placeholder="Describe what to analyze..."
              rows={3}
            />
          )}

          {error && (
            <div className="summarize-error">{error}</div>
          )}

          <button
            className="summarize-generate"
            onClick={handleGenerate}
            disabled={generating || (summaryType === 'custom' && !customPrompt.trim())}
          >
            {generating ? 'Summarizing...' : 'Generate'}
          </button>
        </div>
      )}
    </div>
  )
}
