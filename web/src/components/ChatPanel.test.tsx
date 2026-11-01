import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import type { ChatEvent } from '../api/types'
import { EXAMPLE_QUESTIONS } from '../lib/examples'
import { ChatPanel } from './ChatPanel'

async function* events(...list: ChatEvent[]): AsyncGenerator<ChatEvent> {
  for (const e of list) yield e
}

describe('ChatPanel', () => {
  it('shows the question and the final answer', async () => {
    const send = vi.fn(() =>
      events(
        { type: 'session', session_id: 's1' },
        { type: 'tool', name: 'get_current_price', ok: true },
        { type: 'token', text: 'It is ' },
        { type: 'token', text: '5.0 c/kWh' },
        { type: 'done', answer: 'Right now: 5.0 c/kWh incl. VAT.', tools_used: [], unsupported_numbers: [] },
      ),
    )
    render(<ChatPanel send={send} />)
    await userEvent.type(screen.getByLabelText('Your question'), 'Price now?')
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }))

    expect(await screen.findByText('Right now: 5.0 c/kWh incl. VAT.')).toBeInTheDocument()
    expect(screen.getByText('Price now?')).toBeInTheDocument()
    expect(send).toHaveBeenCalledWith('Price now?', null)
  })

  it('sends the example question and reuses the session id', async () => {
    const send = vi
      .fn()
      .mockReturnValueOnce(
        events(
          { type: 'session', session_id: 's1' },
          { type: 'done', answer: 'First.', tools_used: [], unsupported_numbers: [] },
        ),
      )
      .mockReturnValueOnce(events({ type: 'done', answer: 'Second.', tools_used: [], unsupported_numbers: [] }))
    render(<ChatPanel send={send} />)
    await userEvent.click(screen.getByRole('button', { name: EXAMPLE_QUESTIONS[0] }))
    await screen.findByText('First.')
    await userEvent.click(screen.getByRole('button', { name: EXAMPLE_QUESTIONS[1] }))
    await screen.findByText('Second.')
    expect(send).toHaveBeenNthCalledWith(1, EXAMPLE_QUESTIONS[0], null)
    expect(send).toHaveBeenNthCalledWith(2, EXAMPLE_QUESTIONS[1], 's1')
  })

  it('warns when the guardrail flagged numbers', async () => {
    const send = vi.fn(() =>
      events({ type: 'done', answer: 'About 9 c/kWh.', tools_used: [], unsupported_numbers: ['9'] }),
    )
    render(<ChatPanel send={send} />)
    await userEvent.click(screen.getByRole('button', { name: EXAMPLE_QUESTIONS[0] }))
    expect(await screen.findByText(/could not be verified/)).toBeInTheDocument()
  })

  it('shows a friendly message when rate limited', async () => {
    const send = vi.fn(() => {
      throw new ApiError(429, 'Too many questions')
    })
    render(<ChatPanel send={send} />)
    await userEvent.click(screen.getByRole('button', { name: EXAMPLE_QUESTIONS[0] }))
    expect(await screen.findByText(/wait a moment/)).toBeInTheDocument()
  })

  it('disables the Ask button for an empty question', () => {
    render(<ChatPanel send={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Ask' })).toBeDisabled()
  })
})
