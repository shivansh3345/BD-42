import { useState } from 'react'
import ChatPanel from './components/ChatPanel'
import FactsPanel from './components/FactsPanel'

const SESSION_STORAGE_KEY = 'bd42_session_id'

function getOrCreateSessionId() {
  if (typeof window === 'undefined') return ''
  let id = localStorage.getItem(SESSION_STORAGE_KEY)
  if (!id) {
    id = crypto.randomUUID()
    localStorage.setItem(SESSION_STORAGE_KEY, id)
  }
  return id
}

export default function App() {
  const [sessionId, setSessionId] = useState(() => getOrCreateSessionId())
  const [factsOpen, setFactsOpen] = useState(false)
  const [factsRefreshKey, setFactsRefreshKey] = useState(0)

  function handleNewSession() {
    const newId = crypto.randomUUID()
    localStorage.setItem(SESSION_STORAGE_KEY, newId)
    setSessionId(newId)
    setFactsRefreshKey((k) => k + 1)
  }

  function handleChatComplete() {
    setFactsRefreshKey((k) => k + 1)
  }

  return (
    <div className="h-screen w-screen flex">
      <div className={factsOpen ? 'flex-1 min-w-0' : 'w-full'}>
        <ChatPanel
          sessionId={sessionId}
          onChatComplete={handleChatComplete}
          onReset={handleNewSession}
          onToggleFacts={() => setFactsOpen((v) => !v)}
          factsOpen={factsOpen}
        />
      </div>

      {factsOpen && (
        <div className="w-[360px] flex-shrink-0">
          <FactsPanel
            sessionId={sessionId}
            refreshKey={factsRefreshKey}
            onClose={() => setFactsOpen(false)}
          />
        </div>
      )}
    </div>
  )
}
