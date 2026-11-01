import type { QualityColour, QualitySummary } from '../api/types'

// Status colour never carries meaning alone: every state has an icon and a word.
const STATES: Record<QualityColour, { icon: string; label: string }> = {
  green: { icon: '✓', label: 'Data OK' },
  yellow: { icon: '!', label: 'Data: check' },
  red: { icon: '✕', label: 'Data problem' },
  unknown: { icon: '?', label: 'Data: unknown' },
}

interface Props {
  summary: QualitySummary | null
  error: string | null
}

export function QualityBadge({ summary, error }: Props) {
  const colour: QualityColour = error || !summary ? 'unknown' : summary.overall
  const { icon, label } = STATES[colour]
  const issues = summary
    ? Object.entries(summary.checks)
        .filter(([, status]) => status === 'warn' || status === 'fail')
        .map(([name, status]) => `${name}: ${status}`)
    : []
  const title = error
    ? `Quality status unavailable (${error})`
    : issues.length
      ? issues.join(', ')
      : 'All data-quality checks passed'

  return (
    <span className={`badge badge--${colour}`} title={title} role="status">
      <span className="badge__icon" aria-hidden="true">
        {icon}
      </span>
      {label}
    </span>
  )
}
