import { useState, useRef, useEffect } from 'react'

const API_URL = 'http://localhost:8000'

export default function ChatPanel({ sessionId, onChatComplete, onReset, onToggleFacts, factsOpen }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)
  const scrollRef = useRef(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: 'smooth',
    })
  }, [messages, isLoading])

  useEffect(() => {
    setMessages([])
    setError(null)
  }, [sessionId])

  async function sendMessage(text) {
    const trimmed = text.trim()
    if (!trimmed || isLoading) return

    const userMsg = { role: 'user', content: trimmed, ts: Date.now() }
    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setIsLoading(true)
    setError(null)

    try {
      const res = await fetch(`${API_URL}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: trimmed,
          session_id: sessionId,
          context: {},
        }),
      })

      if (!res.ok) {
        throw new Error(`Server error: ${res.status}`)
      }

      const data = await res.json()
      const assistantMsg = {
        role: 'assistant',
        content: data.reply,
        ts: Date.now(),
        facts: data.fact_captured,
      }
      setMessages((prev) => [...prev, assistantMsg])
      onChatComplete?.()
    } catch (e) {
      setError(e.message || 'Could not reach BD-42. Is the backend running?')
    } finally {
      setIsLoading(false)
    }
  }

  function handleSubmit(e) {
    e.preventDefault()
    sendMessage(input)
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage(input)
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <header className="border-b border-white/10 px-5 py-3 flex items-center justify-between flex-shrink-0">
        <div>
          <h1 className="text-base font-medium tracking-tight">BD-42</h1>
          <p className="text-[10px] text-white/40 font-mono mt-0.5">
            session · {sessionId.slice(0, 8)}
          </p>
        </div>
        <div className="flex gap-2 text-xs">
          <button
            onClick={onToggleFacts}
            className="px-3 py-1.5 rounded border border-white/10 hover:bg-white/5 transition"
            type="button"
          >
            {factsOpen ? 'Hide facts' : 'Show facts'}
          </button>
          <button
            onClick={onReset}
            className="px-3 py-1.5 rounded border border-white/10 hover:bg-white/5 transition"
            type="button"
          >
            New session
          </button>
        </div>
      </header>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-6">
        {messages.length === 0 && !isLoading ? (
          <div className="h-full flex flex-col items-center justify-center text-center">
            <div className="text-white/30 text-sm">Say hi to BD-42.</div>
            <div className="text-white/20 text-xs mt-2 max-w-sm">
              Try telling it{' '}
              <span className="text-white/40">"my favorite game is X"</span>,
              chat about other things, then ask something tangential later. Watch it remember.
            </div>
          </div>
        ) : (
          <div className="space-y-4 max-w-3xl mx-auto">
            {messages.map((m, i) => (
              <div
                key={i}
                className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-[80%] px-4 py-2.5 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap ${
                    m.role === 'user'
                      ? 'bg-white text-black'
                      : 'bg-white/5 border border-white/10 text-white'
                  }`}
                >
                  {m.content}
                  {m.facts && m.facts.length > 0 && (
                    <div className="mt-2 pt-2 border-t border-white/10 text-[11px] text-emerald-400/80 space-y-0.5">
                      {m.facts.map((f, fi) => (
                        <div key={fi}>
                          remembered:{' '}
                          <span className="text-white/60">{f.content}</span>
                          <span className="text-white/30"> · {f.category}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}

            {isLoading && (
              <div className="flex justify-start">
                <div className="bg-white/5 border border-white/10 px-4 py-3 rounded-2xl">
                  <TypingDots />
                </div>
              </div>
            )}

            {error && (
              <div className="text-xs text-red-400/80 text-center pt-2">
                {error}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Composer */}
      <form
        onSubmit={handleSubmit}
        className="border-t border-white/10 px-5 py-4 flex-shrink-0"
      >
        <div className="max-w-3xl mx-auto flex gap-2 items-end">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Message BD-42…"
            rows={1}
            className="flex-1 bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm placeholder-white/30 resize-none focus:outline-none focus:border-white/30 transition"
            style={{ minHeight: '42px', maxHeight: '160px' }}
            disabled={isLoading}
          />
          <button
            type="submit"
            disabled={!input.trim() || isLoading}
            className="px-4 py-2.5 bg-white text-black rounded-xl text-sm font-medium disabled:opacity-30 disabled:cursor-not-allowed hover:bg-white/90 transition"
          >
            Send
          </button>
        </div>
      </form>
    </div>
  )
}

function TypingDots() {
  return (
    <div className="flex gap-1.5">
      <span
        className="w-1.5 h-1.5 rounded-full bg-white/50 animate-pulse"
        style={{ animationDelay: '0ms', animationDuration: '1.2s' }}
      />
      <span
        className="w-1.5 h-1.5 rounded-full bg-white/50 animate-pulse"
        style={{ animationDelay: '200ms', animationDuration: '1.2s' }}
      />
      <span
        className="w-1.5 h-1.5 rounded-full bg-white/50 animate-pulse"
        style={{ animationDelay: '400ms', animationDuration: '1.2s' }}
      />
    </div>
  )
}
