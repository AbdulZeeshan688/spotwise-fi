import { useRef, useState, type FormEvent } from 'react'
import { ApiError, streamChat } from '../api/client'
import type { ChatEvent } from '../api/types'
import { EXAMPLE_QUESTIONS } from '../lib/examples'

type Send = (message: string, sessionId: string | null) => AsyncIterable<ChatEvent>

interface Message {
  id: number
  role: 'user' | 'assistant'
  text: string
  status?: string // e.g. "Checking prices…" while tools run
  warning?: string
  error?: boolean
}

interface Props {
  send?: Send // injectable for tests
}

function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 429) return 'Too many questions in a short time. Please wait a moment.'
    if (err.status === 503) return 'The assistant is not available right now.'
    return err.message
  }
  return 'Could not reach the server. Is the API running?'
}

export function ChatPanel({ send = streamChat }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const sessionId = useRef<string | null>(null)
  const nextId = useRef(1)

  function update(id: number, change: (m: Message) => Message) {
    setMessages((all) => all.map((m) => (m.id === id ? change(m) : m)))
  }

  async function ask(question: string) {
    const text = question.trim()
    if (!text || busy) return
    const answerId = nextId.current + 1
    nextId.current += 2
    setMessages((all) => [
      ...all,
      { id: answerId - 1, role: 'user', text },
      { id: answerId, role: 'assistant', text: '', status: 'Thinking…' },
    ])
    setInput('')
    setBusy(true)
    try {
      for await (const event of send(text, sessionId.current)) {
        switch (event.type) {
          case 'session':
            sessionId.current = event.session_id
            break
          case 'tool':
            update(answerId, (m) => ({ ...m, status: 'Checking prices…' }))
            break
          case 'token':
            update(answerId, (m) => ({ ...m, text: m.text + event.text, status: undefined }))
            break
          case 'done':
            // The final answer replaces the streamed text (it's the checked version)
            update(answerId, (m) => ({
              ...m,
              text: event.answer,
              status: undefined,
              warning: event.unsupported_numbers.length
                ? 'Some numbers in this answer could not be verified against the data.'
                : undefined,
            }))
            break
          case 'error':
            update(answerId, (m) => ({ ...m, text: event.message, status: undefined, error: true }))
            break
        }
      }
    } catch (err) {
      update(answerId, (m) => ({ ...m, text: errorText(err), status: undefined, error: true }))
    } finally {
      setBusy(false)
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    void ask(input)
  }

  return (
    <section className="chat" aria-labelledby="chat-title">
      <h2 id="chat-title">Ask SpotWise</h2>
      <div className="chat__log" aria-live="polite">
        {messages.length === 0 && (
          <p className="chat__empty">Ask about Finnish electricity prices, or try a question below.</p>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`msg msg--${m.role}${m.error ? ' msg--error' : ''}`}>
            <span className="visually-hidden">{m.role === 'user' ? 'You:' : 'SpotWise:'}</span>
            {m.text && <p>{m.text}</p>}
            {m.status && <p className="msg__status">{m.status}</p>}
            {m.warning && <p className="msg__warning">⚠ {m.warning}</p>}
          </div>
        ))}
      </div>
      <div className="chips" role="group" aria-label="Example questions">
        {EXAMPLE_QUESTIONS.map((q) => (
          <button key={q} type="button" className="chip" disabled={busy} onClick={() => void ask(q)}>
            {q}
          </button>
        ))}
      </div>
      <form className="chat__form" onSubmit={onSubmit}>
        <label htmlFor="chat-input" className="visually-hidden">
          Your question
        </label>
        <input
          id="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="e.g. Cheapest 2 hours tomorrow?"
          maxLength={1000}
          autoComplete="off"
        />
        <button type="submit" disabled={busy || !input.trim()}>
          {busy ? 'Asking…' : 'Ask'}
        </button>
      </form>
    </section>
  )
}
