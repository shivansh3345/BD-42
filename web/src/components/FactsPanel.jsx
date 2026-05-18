import { useState, useEffect } from 'react'

const API_URL = 'http://localhost:8000'

export default function FactsPanel({ sessionId, refreshKey, onClose }) {
  const [facts, setFacts] = useState([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false

    async function fetchFacts() {
      setIsLoading(true)
      setError(null)
      try {
        const res = await fetch(`${API_URL}/facts/${sessionId}`)
        if (!res.ok) throw new Error(`Server error: ${res.status}`)
        const data = await res.json()
        if (!cancelled) {
          setFacts(data.facts || [])
        }
      } catch (e) {
        if (!cancelled) setError(e.message || 'Could not load facts')
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }

    fetchFacts()
    return () => {
      cancelled = true
    }
  }, [sessionId, refreshKey])

  const sortedFacts = [...facts].sort(
    (a, b) => (b.importance ?? 0) - (a.importance ?? 0),
  )

  return (
    <div className="flex flex-col h-full border-l border-white/10 bg-black/40">
      <header className="border-b border-white/10 px-5 py-3 flex items-center justify-between flex-shrink-0">
        <div>
          <h2 className="text-sm font-medium">Known about you</h2>
          <p className="text-[10px] text-white/40 mt-0.5">
            {facts.length} {facts.length === 1 ? 'fact' : 'facts'} captured
          </p>
        </div>
        <button
          onClick={onClose}
          className="text-white/50 hover:text-white/80 transition w-7 h-7 flex items-center justify-center rounded hover:bg-white/5"
          aria-label="Close facts panel"
          type="button"
        >
          ×
        </button>
      </header>

      <div className="flex-1 overflow-y-auto px-5 py-4">
        {isLoading && facts.length === 0 && (
          <div className="text-white/30 text-xs text-center">Loading…</div>
        )}

        {error && (
          <div className="text-red-400/80 text-xs text-center">{error}</div>
        )}

        {!isLoading && facts.length === 0 && !error && (
          <div className="text-white/30 text-xs text-center pt-8 leading-relaxed">
            Nothing yet. Tell BD-42 something about you — preferences,
            interests, what you do — and this panel fills up.
          </div>
        )}

        <ul className="space-y-2.5">
          {sortedFacts.map((fact, i) => (
            <li
              key={i}
              className="p-3 rounded-lg bg-white/5 border border-white/10"
            >
              <div className="flex items-baseline gap-2">
                <span className="text-[10px] uppercase tracking-wider text-emerald-400/80">
                  {fact.category || 'general'}
                </span>
                {fact.importance != null && (
                  <span className="text-[10px] text-white/30 ml-auto">
                    {Math.round(fact.importance * 100)}%
                  </span>
                )}
              </div>
              <p className="text-sm text-white/90 mt-1.5 leading-relaxed">
                {fact.content}
              </p>
              {fact.timestamp && (
                <p className="text-[10px] text-white/30 mt-1.5 font-mono">
                  {formatTimestamp(fact.timestamp)}
                </p>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

function formatTimestamp(ts) {
  const date = new Date(ts * 1000) // backend stores unix seconds
  const diffMs = Date.now() - date.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1) return 'just now'
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24) return `${diffHour}h ago`
  const diffDay = Math.floor(diffHour / 24)
  if (diffDay < 7) return `${diffDay}d ago`
  return date.toLocaleDateString()
}
