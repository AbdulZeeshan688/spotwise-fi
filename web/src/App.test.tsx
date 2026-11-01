import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'

describe('App', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    // A server that never answers (like a sleeping free host)
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('explains a slow first load (free server waking up)', async () => {
    render(<App />)
    expect(screen.getByText('Loading prices…')).toBeInTheDocument()
    await act(() => vi.advanceTimersByTimeAsync(5000))
    expect(screen.getByText(/Waking up the free server/)).toBeInTheDocument()
  })
})
