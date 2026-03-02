import type { PerturbationReportResponse, DivergenceMetrics } from '../../api/types.ts'
import { DivergenceBar } from './DivergenceBar.tsx'

interface PerturbationReportViewProps {
  report: PerturbationReportResponse
  onNavigateToNode: (nodeId: string) => void
  onDelete: (reportId: string) => void
}

export function PerturbationReportView({ report, onNavigateToNode, onDelete }: PerturbationReportViewProps) {
  const controlStep = report.steps.find(s => s.type === 'control')
  const perturbationSteps = report.steps.filter(s => s.type !== 'control')

  // Sort perturbations by divergence (most impactful first)
  const sorted = [...perturbationSteps].sort((a, b) => {
    const divA = report.divergence.find(d => d.label === a.label)
    const divB = report.divergence.find(d => d.label === b.label)
    return (divB?.word_diff_ratio ?? 0) - (divA?.word_diff_ratio ?? 0)
  })

  return (
    <div className="perturbation-report">
      <div className="perturbation-report-header">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '0.5rem' }}>
          <div>
            <div style={{ fontSize: '0.82rem', fontWeight: 600 }}>
              {report.provider}/{report.model}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              {report.steps.length} steps &middot; {new Date(report.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
            </div>
          </div>
          <button
            onClick={() => onDelete(report.report_id)}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)', fontSize: '0.9rem' }}
            aria-label="Delete report"
          >
            &times;
          </button>
        </div>
      </div>

      {controlStep && (
        <div className="perturbation-step-card" style={{ marginTop: '0.5rem' }}>
          <div style={{ fontSize: '0.78rem', fontWeight: 600, marginBottom: '0.25rem' }}>
            Control (unmodified)
          </div>
          <div
            className="perturbation-step-content"
            onClick={() => onNavigateToNode(controlStep.node_id)}
            style={{ cursor: 'pointer' }}
          >
            {controlStep.content.length > 200
              ? controlStep.content.slice(0, 200) + '...'
              : controlStep.content}
          </div>
          {controlStep.latency_ms != null && (
            <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>
              {controlStep.latency_ms}ms
            </div>
          )}
        </div>
      )}

      {sorted.map((step, i) => {
        const div = report.divergence.find(d => d.label === step.label)
        return (
          <div key={i} className="perturbation-step-card" style={{ marginTop: '0.5rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.25rem' }}>
              <div style={{ fontSize: '0.78rem', fontWeight: 600 }}>
                {step.label}
              </div>
              <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>
                {step.type}
              </span>
            </div>
            <div
              className="perturbation-step-content"
              onClick={() => onNavigateToNode(step.node_id)}
              style={{ cursor: 'pointer' }}
            >
              {step.content.length > 200
                ? step.content.slice(0, 200) + '...'
                : step.content}
            </div>
            {div && <StepDivergence metrics={div} />}
            {step.latency_ms != null && (
              <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>
                {step.latency_ms}ms
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function StepDivergence({ metrics }: { metrics: DivergenceMetrics }) {
  return (
    <div style={{ marginTop: '0.4rem', display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
      <DivergenceBar value={metrics.word_diff_ratio} label="Word diff" />
      <DivergenceBar value={metrics.edit_distance} label="Edit dist" />
      <DivergenceBar value={metrics.length_ratio > 0 ? Math.abs(1 - metrics.length_ratio) : 0} label="Len delta" />
      {metrics.certainty_delta != null && (
        <DivergenceBar value={metrics.certainty_delta} label="Certainty" centered />
      )}
    </div>
  )
}
