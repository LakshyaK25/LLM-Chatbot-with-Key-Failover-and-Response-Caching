import { useRef, useState } from 'react'

const API_URL = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '')

function newSessionId() {
  const unique = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`
  return `s-${unique}`
}

function errorMessage(status, detail) {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => item?.msg || 'Invalid input')
    return `Invalid request: ${messages.join('; ')}`
  }
  if (status === 503) return 'The AI service is unavailable right now. Please try again.'
  return 'The request could not be completed. Please try again.'
}

function Metadata({ metadata }) {
  if (!metadata) return null
  return (
    <div className="meta" aria-label="Response metadata">
      <span className={`source-pill ${metadata.resolution_source === 'LLM_CACHE' ? 'cache' : 'live'}`}>
        <span data-testid="meta-source">{metadata.resolution_source}</span>
      </span>
      <span className="meta-item">
        <span className="meta-label">Model</span>
        <span data-testid="meta-model">{metadata.model}</span>
      </span>
      <span className="meta-item">
        <span className="meta-label">Latency</span>
        <span data-testid="meta-latency">{metadata.latency_ms} ms</span>
      </span>
      <span className="meta-item">
        <span className="meta-label">Input tokens</span>
        <span data-testid="meta-input-tokens">{metadata.input_tokens}</span>
      </span>
      <span className="meta-item">
        <span className="meta-label">Output tokens</span>
        <span data-testid="meta-output-tokens">{metadata.output_tokens}</span>
      </span>
    </div>
  )
}

export default function App() {
  const [sessionId] = useState(newSessionId)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const bottomRef = useRef(null)

  async function send(event) {
    event?.preventDefault()
    const text = input.trim()
    if (!text || loading) return

    setLoading(true)
    setError('')
    setMessages((current) => [...current, { id: `${Date.now()}-u`, role: 'user', content: text }])
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })

    try {
      const response = await fetch(`${API_URL}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, message: text }),
      })

      let data = {}
      try {
        data = await response.json()
      } catch {
        // A non-JSON response is still handled as a readable error below.
      }

      if (!response.ok) {
        throw new Error(errorMessage(response.status, data?.detail))
      }

      setInput('')
      setMessages((current) => [
        ...current,
        {
          id: `${Date.now()}-a`,
          role: 'assistant',
          content: data.reply,
          metadata: data.metadata,
        },
      ])
    } catch (err) {
      const raw = err?.message || ''
      setError(
        raw === 'Failed to fetch'
          ? `Could not reach the backend at ${API_URL}. Check that it is running.`
          : raw || 'The request could not be completed. Please try again.',
      )
    } finally {
      setLoading(false)
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }

  function handleKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      send(event)
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">L</span>
          <div>
            <h1>Lyftr AI Chatbot</h1>
            <p>Failover &amp; cached responses</p>
          </div>
        </div>
        <div className="session-chip" title="Session ID generated on page load">
          <span className="dot" /> {sessionId}
        </div>
      </header>

      <main className="chat-area">
        <div className="chat-inner">
          {messages.length === 0 && !error && (
            <div className="empty-state">
              <div className="empty-icon">✦</div>
              <h2>Ask me anything</h2>
              <p>Messages are remembered within this session.</p>
            </div>
          )}

          {messages.map((message) =>
            message.role === 'user' ? (
              <div className="message user" key={message.id}>
                <div className="avatar">You</div>
                <div className="bubble">{message.content}</div>
              </div>
            ) : (
              <div className="message assistant" data-testid="assistant-message" key={message.id}>
                <div className="avatar ai">AI</div>
                <div className="answer-block">
                  <div className="bubble">{message.content}</div>
                  <Metadata metadata={message.metadata} />
                </div>
              </div>
            ),
          )}

          {loading && (
            <div className="message assistant loading-row">
              <div className="avatar ai">AI</div>
              <div className="typing"><i /><i /><i /></div>
            </div>
          )}

          {error && (
            <div className="error-bubble" role="alert">
              <strong>Error</strong>
              <span>{error}</span>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </main>

      <form className="composer" onSubmit={send}>
        <textarea
          data-testid="chat-input"
          aria-label="Message"
          placeholder="Type your message…  (Enter to send)"
          value={input}
          rows={1}
          disabled={loading}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={handleKeyDown}
        />
        <button data-testid="send-button" type="submit" disabled={loading || !input.trim()}>
          {loading ? 'Sending…' : 'Send'}
        </button>
      </form>
    </div>
  )
}
