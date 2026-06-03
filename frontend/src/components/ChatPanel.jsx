import React, { useState, useRef, useEffect } from 'react'
import { useStore } from '../store'
import { activeRows, siteSummary } from '../utils'

const API_URL = import.meta.env.VITE_API_URL || ''

function buildContext(results, activeSite) {
  if (!results) return 'No reconciliation data loaded yet.'
  const sites = Object.keys(results)
  const lines = [`Loaded sites: ${sites.join(', ')}`]
  if (activeSite && results[activeSite]) {
    const s = results[activeSite]
    const sum = siteSummary(s)
    const rows = activeRows(s.reconciliation)
    lines.push(`\nActive site: ${activeSite}`)
    lines.push(`Foreseer devices: ${sum.foreseer_devices}, LinX assets: ${sum.linx_assets}`)
    lines.push(`Avg match score: ${sum.avg_score ?? 'N/A'}`)
    lines.push(`Matched types: ${sum.matched_types}, Needs review: ${sum.needs_review}`)
    lines.push(`Foreseer only: ${sum.foreseer_only}, LinX only: ${sum.linx_only}`)
    const issues = rows.filter(r => r.match_status !== 'Match' && r.match_status !== 'No records in either system' && (r.foreseer_count > 0 || r.linx_count > 0))
    if (issues.length) {
      lines.push(`\nTop issues:`)
      issues.slice(0, 8).forEach(r => {
        lines.push(`  - ${r.device_type}: F=${r.foreseer_count} L=${r.linx_count} (${r.match_status}) score=${r.match_score}`)
      })
    }
  }
  return lines.join('\n')
}

const SUGGESTIONS = [
  'What are the biggest gaps for this site?',
  'Which device types need the most attention?',
  'Why might Fuse Alarm Panels be missing from LinX?',
  'How do I interpret the match score?',
  'What should I do with Foreseer Only assets?',
]

export default function ChatPanel() {
  const { results, activeSite } = useStore()
  const [open,     setOpen]     = useState(false)
  const [messages, setMessages] = useState([
    { role: 'ai', text: 'Hi! I can help you understand the reconciliation results. Ask me anything about the data, or click a suggestion below.' }
  ])
  const [input,    setInput]    = useState('')
  const [loading,  setLoading]  = useState(false)
  const bottomRef = useRef()

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function sendMessage(text) {
    if (!text.trim() || loading) return
    const userMsg = text.trim()
    setInput('')
    setMessages(prev => [...prev, { role: 'user', text: userMsg }])
    setLoading(true)

    try {
      const context = buildContext(results, activeSite)
      const res = await fetch(`${API_URL}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userMsg, context }),
      })
      if (!res.ok) throw new Error(`Server error ${res.status}`)
      const data = await res.json()
      setMessages(prev => [...prev, { role: 'ai', text: data.reply }])
    } catch (e) {
      setMessages(prev => [...prev, { role: 'ai', text: `Sorry, I couldn't connect to the AI service. Error: ${e.message}` }])
    } finally {
      setLoading(false)
    }
  }

  function handleKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(input) }
  }

  return (
    <>
      <button className="chat-fab" onClick={() => setOpen(o => !o)} title="Ask the AI assistant">
        {open ? '✕' : '💬'}
      </button>

      {open && (
        <div className="chat-panel">
          <div className="chat-header">
            <span className="chat-header-icon">🤖</span>
            <span className="chat-header-title">GIG Assistant</span>
            <span style={{ fontSize: 10, color: 'var(--gray-400)' }}>Powered by Claude</span>
            <button className="chat-close" onClick={() => setOpen(false)}>✕</button>
          </div>

          <div className="chat-messages">
            {messages.map((m, i) => (
              <div key={i} className={`chat-msg ${m.role}`}>
                <div className="chat-bubble" style={{ whiteSpace: 'pre-wrap' }}>{m.text}</div>
              </div>
            ))}
            {loading && (
              <div className="chat-msg ai">
                <div className="chat-bubble" style={{ color: 'var(--gray-400)', fontStyle: 'italic' }}>Thinking...</div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* Suggestion chips */}
          {messages.length <= 2 && (
            <div style={{ padding: '6px 12px', display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {SUGGESTIONS.map((s, i) => (
                <button key={i} onClick={() => sendMessage(s)}
                  style={{
                    fontSize: 10, padding: '3px 8px', borderRadius: 10,
                    border: '1px solid var(--gray-300)', background: 'white',
                    cursor: 'pointer', color: 'var(--gray-600)',
                  }}>
                  {s}
                </button>
              ))}
            </div>
          )}

          <div className="chat-input-row">
            <textarea
              className="chat-input"
              rows={2}
              placeholder="Ask about the results..."
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKey}
            />
            <button className="chat-send" onClick={() => sendMessage(input)} disabled={loading || !input.trim()}>
              Send
            </button>
          </div>
        </div>
      )}
    </>
  )
}
