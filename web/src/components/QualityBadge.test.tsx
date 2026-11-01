import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { QualitySummary } from '../api/types'
import { QualityBadge } from './QualityBadge'

const summary = (overall: QualitySummary['overall'], checks: QualitySummary['checks'] = {}): QualitySummary => ({
  overall,
  run_at: '2025-11-15T10:00:00+02:00',
  checks,
  results: [],
})

describe('QualityBadge', () => {
  it('shows a word and an icon, not only a colour', () => {
    render(<QualityBadge summary={summary('green')} error={null} />)
    expect(screen.getByRole('status')).toHaveTextContent('Data OK')
    expect(screen.getByRole('status')).toHaveTextContent('✓')
  })

  it('lists failing checks in the tooltip', () => {
    render(<QualityBadge summary={summary('red', { completeness: 'fail', spikes: 'pass' })} error={null} />)
    expect(screen.getByRole('status')).toHaveTextContent('Data problem')
    expect(screen.getByRole('status')).toHaveAttribute('title', 'completeness: fail')
  })

  it('is "unknown" when the API call failed', () => {
    render(<QualityBadge summary={null} error="Network error" />)
    expect(screen.getByRole('status')).toHaveTextContent('Data: unknown')
  })
})
