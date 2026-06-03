import React, { useState, useEffect } from 'react'

// Team password — change this to whatever your team wants
// This is stored as a simple hash so it's not plaintext in the code
const PASS_HASH = btoa('GiG@Cmcst#9x2Kv!mR7qL')
const STORAGE_KEY = 'gig_auth'

function check(input) {
  return btoa(input.trim()) === PASS_HASH
}

export function useAuth() {
  return localStorage.getItem(STORAGE_KEY) === PASS_HASH
}

export default function PasswordGate({ children }) {
  const [authed,  setAuthed]  = useState(false)
  const [input,   setInput]   = useState('')
  const [error,   setError]   = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (localStorage.getItem(STORAGE_KEY) === PASS_HASH) setAuthed(true)
    setLoading(false)
  }, [])

  function handleSubmit(e) {
    e.preventDefault()
    if (check(input)) {
      localStorage.setItem(STORAGE_KEY, PASS_HASH)
      setAuthed(true)
      setError(false)
    } else {
      setError(true)
      setInput('')
    }
  }

  if (loading) return null
  if (authed)  return children

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center',
      justifyContent: 'center', background: '#003a5e',
    }}>
      <div style={{
        background: 'white', borderRadius: 12, padding: '40px 48px',
        width: 380, boxShadow: '0 20px 60px rgba(0,0,0,.3)',
        textAlign: 'center',
      }}>
        {/* Logo */}
        <div style={{ fontSize: 28, fontWeight: 800, color: '#0061A0', marginBottom: 4 }}>
          GIG<span style={{ fontWeight: 400, opacity: .6 }}>tool</span>
        </div>
        <div style={{ fontSize: 11, color: '#94a3b8', textTransform: 'uppercase',
          letterSpacing: '1px', marginBottom: 32 }}>
          Data Integrity Platform
        </div>

        <div style={{ fontSize: 15, fontWeight: 600, color: '#334155', marginBottom: 8 }}>
          Team Access
        </div>
        <div style={{ fontSize: 13, color: '#64748b', marginBottom: 28 }}>
          Enter the team password to continue
        </div>

        <form onSubmit={handleSubmit}>
          <input
            type="password"
            value={input}
            onChange={e => { setInput(e.target.value); setError(false) }}
            placeholder="Enter password"
            autoFocus
            style={{
              width: '100%', padding: '11px 14px', fontSize: 14,
              border: `1.5px solid ${error ? '#dc2626' : '#e2e8f0'}`,
              borderRadius: 7, outline: 'none', marginBottom: 12,
              transition: 'border-color .15s',
            }}
            onFocus={e => e.target.style.borderColor = '#0061A0'}
            onBlur={e => e.target.style.borderColor = error ? '#dc2626' : '#e2e8f0'}
          />
          {error && (
            <div style={{ color: '#dc2626', fontSize: 12, marginBottom: 10 }}>
              Incorrect password. Please try again.
            </div>
          )}
          <button type="submit" style={{
            width: '100%', background: '#0061A0', color: 'white',
            border: 'none', borderRadius: 7, padding: '11px 0',
            fontSize: 14, fontWeight: 700, cursor: 'pointer',
            transition: 'background .15s',
          }}
            onMouseEnter={e => e.target.style.background = '#004d80'}
            onMouseLeave={e => e.target.style.background = '#0061A0'}
          >
            Sign In
          </button>
        </form>

        <div style={{ marginTop: 24, fontSize: 11, color: '#cbd5e1' }}>
          Comcast GIG Initiative · Internal Use Only
        </div>
      </div>
    </div>
  )
}
