/**
 * Error panel with retry/settings/dismiss actions,
 * extracted from LinearView for reuse by ChatView and CompletionView.
 */

import type { GenerateRequest } from '../../api/types.ts'
import type { ForkTarget } from './useViewShared.ts'

interface GenerationErrorInfo {
  parentNodeId: string
  provider: string
  model: string | null
  systemPrompt: string | null
  errorMessage: string
}

interface GenerationErrorPanelProps {
  generationError: GenerationErrorInfo
  leafNodeId: string | null
  onRetry: (parentNodeId: string, overrides: GenerateRequest) => void
  onChangeSettings: (target: ForkTarget) => void
  onDismiss: () => void
}

export function GenerationErrorPanel({
  generationError,
  leafNodeId,
  onRetry,
  onChangeSettings,
  onDismiss,
}: GenerationErrorPanelProps) {
  // Only show when the error is at the current leaf
  if (leafNodeId !== generationError.parentNodeId) return null

  return (
    <div className="generation-error-panel">
      <div className="generation-error-header">Generation failed</div>
      <div className="generation-error-message">{generationError.errorMessage}</div>
      <div className="generation-error-actions">
        <button
          className="generation-error-retry"
          onClick={() => {
            onRetry(generationError.parentNodeId, {
              provider: generationError.provider,
              model: generationError.model ?? undefined,
              system_prompt: generationError.systemPrompt ?? undefined,
            })
          }}
        >
          Retry
        </button>
        <button
          className="generation-error-settings"
          onClick={() => {
            onDismiss()
            onChangeSettings({ parentId: generationError.parentNodeId, mode: 'regenerate' })
          }}
        >
          Change settings
        </button>
        <button className="generation-error-dismiss" onClick={onDismiss}>
          Dismiss
        </button>
      </div>
    </div>
  )
}
