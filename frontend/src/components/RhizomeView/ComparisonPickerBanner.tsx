import './ComparisonPickerBanner.css'

interface ComparisonPickerBannerProps {
  sourceModel: string | null
  sourceTimestamp: string
  sourceResponsePreview: string
  onCancel: () => void
}

function formatTimestamp(isoString: string): string {
  const date = new Date(isoString)
  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
  }) + ' at ' + date.toLocaleTimeString(undefined, {
    hour: 'numeric',
    minute: '2-digit',
  })
}

export function ComparisonPickerBanner({
  sourceModel,
  sourceTimestamp,
  sourceResponsePreview,
  onCancel,
}: ComparisonPickerBannerProps) {
  return (
    <div className="comparison-picker-banner">
      <div className="comparison-picker-header">
        <div className="comparison-picker-title">Pick comparison target</div>
        <button className="comparison-picker-cancel" onClick={onCancel}>
          Cancel
        </button>
      </div>
      <div className="comparison-picker-source">
        <span className="comparison-picker-source-label">Comparing from:</span>
        <span className="comparison-picker-source-model">{sourceModel ?? 'Unknown model'}</span>
        <span className="comparison-picker-source-time">{formatTimestamp(sourceTimestamp)}</span>
      </div>
      <div className="comparison-picker-preview">{sourceResponsePreview}</div>
      <div className="comparison-picker-hint">
        Navigate branches and click an assistant message to compare. Press Esc to cancel.
      </div>
    </div>
  )
}
