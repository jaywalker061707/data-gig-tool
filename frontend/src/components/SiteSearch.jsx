import React, { useState, useRef, useEffect, useMemo } from 'react'

export default function SiteSearch({ sites, value, onChange, placeholder = 'Search sites...' }) {
  const [open,   setOpen]   = useState(false)
  const [query,  setQuery]  = useState('')
  const ref  = useRef()
  const input = useRef()

  const filtered = useMemo(() => {
    if (!query) return sites
    const q = query.toLowerCase()
    return sites.filter(s => s.toLowerCase().includes(q))
  }, [sites, query])

  useEffect(() => {
    function handleClick(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  function select(site) {
    onChange(site)
    setQuery('')
    setOpen(false)
  }

  return (
    <div ref={ref} style={{ position: 'relative', minWidth: 220 }}>
      <div
        onClick={() => { setOpen(o => !o); setTimeout(() => input.current?.focus(), 50) }}
        style={{
          border: '1px solid var(--gray-300)', borderRadius: 6,
          padding: '7px 32px 7px 12px', fontSize: 13, cursor: 'pointer',
          background: 'white', display: 'flex', alignItems: 'center',
          justifyContent: 'space-between', userSelect: 'none',
          minWidth: 220,
        }}
      >
        <span style={{ color: value ? 'var(--gray-900)' : 'var(--gray-400)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {value || placeholder}
        </span>
        <span style={{ position: 'absolute', right: 10, color: 'var(--gray-400)', fontSize: 10 }}>
          {open ? '▲' : '▼'}
        </span>
      </div>

      {open && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, right: 0,
          background: 'white', border: '1px solid var(--gray-300)',
          borderRadius: 6, boxShadow: '0 4px 16px rgba(0,0,0,.12)',
          zIndex: 1000, overflow: 'hidden',
        }}>
          <div style={{ padding: '6px 8px', borderBottom: '1px solid var(--gray-100)' }}>
            <input
              ref={input}
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Type to search..."
              style={{
                width: '100%', border: '1px solid var(--gray-300)', borderRadius: 4,
                padding: '5px 8px', fontSize: 12, outline: 'none',
              }}
              onFocus={e => e.target.style.borderColor = 'var(--comcast-blue)'}
              onBlur={e => e.target.style.borderColor = 'var(--gray-300)'}
            />
          </div>
          <div style={{ maxHeight: 240, overflowY: 'auto' }}>
            {filtered.length === 0 && (
              <div style={{ padding: '10px 12px', fontSize: 12, color: 'var(--gray-400)' }}>No sites match</div>
            )}
            {filtered.map(s => (
              <div
                key={s}
                onClick={() => select(s)}
                style={{
                  padding: '8px 12px', fontSize: 12, cursor: 'pointer',
                  background: s === value ? 'var(--comcast-blue-light)' : 'white',
                  color: s === value ? 'var(--comcast-blue)' : 'var(--gray-800)',
                  fontWeight: s === value ? 600 : 400,
                }}
                onMouseEnter={e => { if (s !== value) e.target.style.background = 'var(--gray-50)' }}
                onMouseLeave={e => { if (s !== value) e.target.style.background = 'white' }}
              >
                {s}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
