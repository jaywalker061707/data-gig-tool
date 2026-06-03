import React, { useState, useMemo } from 'react'
import { useStore } from '../store'
import { activeRows } from '../utils'
import { useEffect } from 'react'

const METHOD_STYLE = {
  'IP Match':      { background: '#dcfce7', color: '#15803d' },
  'Serial Match':  { background: '#d1fae5', color: '#065f46' },
  'Name Match':    { background: '#dbeafe', color: '#1d4ed8' },
  'Foreseer Only': { background: '#fef9c3', color: '#854d0e' },
  'LinX Only':     { background: '#fce7f3', color: '#9d174d' },
}

export default function ReviewTab() {
  const { results, activeSite, setActiveSite } = useStore()
  const [traceFilter, setTraceFilter] = useState('all')
  const [pairFilter,  setPairFilter]  = useState('all')
  const [pairSearch,  setPairSearch]  = useState('')
  const [activePanel, setActivePanel] = useState('pairs') // 'pairs' | 'trace' | 'drilldown'

  const { loadSiteDetail, loadingDetail } = useStore()

  // Trigger on-demand load when this tab opens or site changes
  useEffect(() => {
    if (activeSite && activePanel === 'pairs' || activePanel === 'trace') {
      loadSiteDetail(activeSite)
    }
  }, [activeSite, activePanel])

  const sites    = Object.keys(results || {})
  const siteData = results?.[activeSite]
  const rows     = activeRows(siteData?.reconciliation)
  const trace    = siteData?.prefix_trace  || []
  const pairs    = siteData?.asset_pairs   || []

  const filteredTrace = useMemo(() => {
    if (traceFilter === 'unmatched') return trace.filter(t => t.status === 'No match')
    if (traceFilter === 'matched')   return trace.filter(t => t.status === 'Matched')
    return trace
  }, [trace, traceFilter])

  const filteredPairs = useMemo(() => {
    let p = pairs
    if (pairFilter !== 'all') p = p.filter(x => x.match_method === pairFilter)
    if (pairSearch) {
      const s = pairSearch.toLowerCase()
      p = p.filter(x =>
        (x.foreseer_device || '').toLowerCase().includes(s) ||
        (x.linx_asset_id   || '').toLowerCase().includes(s) ||
        (x.device_type     || '').toLowerCase().includes(s) ||
        (x.foreseer_ip     || '').toLowerCase().includes(s) ||
        (x.linx_ip         || '').toLowerCase().includes(s)
      )
    }
    return p
  }, [pairs, pairFilter, pairSearch])

  const pairCounts = useMemo(() => {
    const c = {}
    pairs.forEach(p => { c[p.match_method] = (c[p.match_method] || 0) + 1 })
    return c
  }, [pairs])

  if (!results) return (
    <div className="empty-state">
      <div className="icon">🔬</div>
      <h3>No results yet</h3>
      <p>Upload files and run the reconciliation first.</p>
    </div>
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* Site + panel switcher */}
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <select className="site-select" value={activeSite || ''} onChange={e => setActiveSite(e.target.value)}>
          {sites.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        {['pairs', 'trace', 'drilldown'].map(p => (
          <button
            key={p}
            onClick={() => setActivePanel(p)}
            style={{
              padding: '6px 14px', borderRadius: 6, border: '1px solid var(--gray-300)',
              background: activePanel === p ? 'var(--comcast-blue)' : 'white',
              color: activePanel === p ? 'white' : 'var(--gray-700)',
              fontWeight: 600, fontSize: 12, cursor: 'pointer',
            }}
          >
            {p === 'pairs' ? 'Asset Pairing' : p === 'trace' ? 'Prefix Trace' : 'Type Drilldown'}
          </button>
        ))}
      </div>

      {/* ── Asset Pairing Panel ── */}
      {activePanel === 'pairs' && (
        <div className="card">
          {loadingDetail && (
            <div style={{ padding: '12px 0', fontSize: 12, color: 'var(--comcast-blue)', display: 'flex', alignItems: 'center', gap: 8 }}>
              <span className="spinner" style={{ borderTopColor: 'var(--comcast-blue)', borderColor: 'var(--gray-200)' }} />
              Loading asset-level detail for {activeSite}...
            </div>
          )}
          <div className="section-header" style={{ marginBottom: 12 }}>
            <div className="section-title">Asset-Level Matching — {activeSite}</div>
            <div style={{ fontSize: 12, color: 'var(--gray-500)' }}>
              {pairs.length} total asset records
            </div>
          </div>

          {/* Method summary chips */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
            {Object.entries(pairCounts).map(([method, count]) => {
              const s = METHOD_STYLE[method] || {}
              return (
                <button
                  key={method}
                  onClick={() => setPairFilter(f => f === method ? 'all' : method)}
                  style={{
                    padding: '4px 12px', borderRadius: 20, border: 'none', cursor: 'pointer',
                    fontSize: 12, fontWeight: 600,
                    background: pairFilter === method ? s.background : 'var(--gray-100)',
                    color: pairFilter === method ? s.color : 'var(--gray-500)',
                    outline: pairFilter === method ? `2px solid ${s.color}` : 'none',
                  }}
                >
                  {method}: {count}
                </button>
              )
            })}
            {pairFilter !== 'all' && (
              <button onClick={() => setPairFilter('all')}
                style={{ padding: '4px 12px', borderRadius: 20, border: '1px solid var(--gray-300)', fontSize: 12, cursor: 'pointer', background: 'white' }}>
                Clear filter
              </button>
            )}
          </div>

          <div style={{ marginBottom: 12 }}>
            <input
              className="search-input"
              placeholder="Search device name, asset ID, IP..."
              value={pairSearch}
              onChange={e => setPairSearch(e.target.value)}
              style={{ width: 340 }}
            />
          </div>

          <div className="table-wrap" style={{ maxHeight: 520, overflow: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>Device Type</th>
                  <th>Match</th>
                  <th>Foreseer Device</th>
                  <th>Foreseer IP</th>
                  <th>Foreseer Serial</th>
                  <th>LinX Asset ID</th>
                  <th>LinX Asset Name</th>
                  <th>LinX IP</th>
                  <th>LinX Serial</th>
                </tr>
              </thead>
              <tbody>
                {filteredPairs.map((p, i) => {
                  const s = METHOD_STYLE[p.match_method] || {}
                  return (
                    <tr key={i} style={{ background: s.background }}>
                      <td style={{ fontSize: 11 }}>{p.device_type}</td>
                      <td>
                        <span style={{ fontSize: 11, fontWeight: 700, color: s.color }}>
                          {p.match_method}
                        </span>
                      </td>
                      <td style={{ fontSize: 11, fontFamily: 'monospace' }}>{p.foreseer_device || '—'}</td>
                      <td style={{ fontSize: 11 }}>{p.foreseer_ip || '—'}</td>
                      <td style={{ fontSize: 11 }}>{p.foreseer_serial || '—'}</td>
                      <td style={{ fontSize: 11, fontFamily: 'monospace' }}>{p.linx_asset_id || '—'}</td>
                      <td style={{ fontSize: 11 }}>{p.linx_asset_name || '—'}</td>
                      <td style={{ fontSize: 11 }}>{p.linx_ip || '—'}</td>
                      <td style={{ fontSize: 11 }}>{p.linx_serial || '—'}</td>
                    </tr>
                  )
                })}
                {!filteredPairs.length && (
                  <tr><td colSpan={9} style={{ textAlign: 'center', padding: 24, color: 'var(--gray-500)' }}>No records match the current filter.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Prefix Trace Panel ── */}
      {activePanel === 'trace' && (
        <div className="card">
          <div className="section-header" style={{ marginBottom: 12 }}>
            <div className="section-title">Prefix Resolution Trace</div>
            <select
              style={{ border: '1px solid var(--gray-300)', borderRadius: 6, padding: '4px 8px', fontSize: 12 }}
              value={traceFilter} onChange={e => setTraceFilter(e.target.value)}
            >
              <option value="all">All ({trace.length})</option>
              <option value="matched">Matched ({trace.filter(t => t.status === 'Matched').length})</option>
              <option value="unmatched">No match ({trace.filter(t => t.status === 'No match').length})</option>
            </select>
          </div>
          <div className="table-wrap" style={{ maxHeight: 520, overflow: 'auto' }}>
            <table>
              <thead>
                <tr><th>Device Name</th><th>Prefix Derived</th><th>Resolved Type</th><th>Status</th></tr>
              </thead>
              <tbody>
                {filteredTrace.map((t, i) => (
                  <tr key={i}>
                    <td style={{ fontSize: 11 }}>{t.device_name}</td>
                    <td style={{ fontFamily: 'monospace', fontSize: 11 }}>{t.combo_key_derived || '—'}</td>
                    <td style={{ fontSize: 11 }}>{t.resolved_type || '—'}</td>
                    <td>
                      <span style={{
                        fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 10,
                        background: t.status === 'Matched' ? 'var(--green-bg)' : 'var(--red-bg)',
                        color: t.status === 'Matched' ? 'var(--green)' : 'var(--red)',
                      }}>{t.status}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Type Drilldown Panel ── */}
      {activePanel === 'drilldown' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <div className="card">
            <div className="section-title" style={{ marginBottom: 10 }}>Data Load Sanity</div>
            {Object.entries(siteData?.sanity || {}).map(([k, v]) => (
              <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--gray-100)', fontSize: 13 }}>
                <span style={{ color: 'var(--gray-500)' }}>{k.replace(/_/g, ' ')}</span>
                <strong>{v}</strong>
              </div>
            ))}
          </div>
          <div className="card">
            <div className="section-title" style={{ marginBottom: 10 }}>Per-Type Asset Lists</div>
            <select className="site-select" style={{ width: '100%', marginBottom: 14 }}
              onChange={e => {}}>
              <option value="">— Select a device type —</option>
              {rows.map(r => (
                <option key={r.device_type} value={r.device_type}>
                  {r.device_type} (F:{r.foreseer_count} L:{r.linx_count})
                </option>
              ))}
            </select>
            <p style={{ fontSize: 12, color: 'var(--gray-500)' }}>
              Use the Asset Pairing tab and filter by device type for full detail.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
