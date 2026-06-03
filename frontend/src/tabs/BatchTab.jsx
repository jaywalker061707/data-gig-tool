import React, { useState, useMemo } from 'react'
import { useStore } from '../store'
import { siteSummary, scoreClass, fmt } from '../utils'

export default function BatchTab() {
  const { results, setActiveSite, setActiveTab } = useStore()
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState({ col: 'avg_score', dir: 1 })

  const summaries = useMemo(() => {
    if (!results) return []
    return Object.values(results).map(siteSummary)
  }, [results])

  const filtered = useMemo(() => {
    let r = summaries
    if (search) r = r.filter(s => s.site.toLowerCase().includes(search.toLowerCase()))
    return [...r].sort((a, b) => {
      const av = a[sort.col] ?? -1, bv = b[sort.col] ?? -1
      return (Number(av) - Number(bv)) * sort.dir
    })
  }, [summaries, search, sort])

  function toggleSort(col) {
    setSort(s => s.col === col ? { col, dir: -s.dir } : { col, dir: -1 })
  }

  function drillSite(site) {
    setActiveSite(site)
    setActiveTab('recon')
  }

  function Th({ col, children }) {
    const active = sort.col === col
    return <th onClick={() => toggleSort(col)}>{children} {active ? (sort.dir === -1 ? '↓' : '↑') : ''}</th>
  }

  if (!results) return <EmptyState />

  const totForeseer = summaries.reduce((a, s) => a + s.foreseer_devices, 0)
  const totLinx     = summaries.reduce((a, s) => a + s.linx_assets, 0)
  const globalScore = summaries.length
    ? Math.round(summaries.filter(s => s.avg_score != null).reduce((a,s) => a + s.avg_score, 0)
        / summaries.filter(s => s.avg_score != null).length)
    : null

  return (
    <div>
      <div className="kpi-row" style={{ marginBottom: 20 }}>
        <div className="kpi-card">
          <div className="kpi-label">Sites</div>
          <div className="kpi-value">{summaries.length}</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Total Foreseer</div>
          <div className="kpi-value">{fmt(totForeseer)}</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Total LinX</div>
          <div className="kpi-value">{fmt(totLinx)}</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Avg Score</div>
          <div className="kpi-value">{globalScore ?? '—'}</div>
        </div>
      </div>

      <div className="controls">
        <input
          className="search-input"
          placeholder="Search site..."
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
        <button
          style={{ marginLeft: 'auto', padding: '7px 16px', border: '1px solid var(--gray-300)', borderRadius: 6, cursor: 'pointer', fontSize: 13, background: 'white' }}
          onClick={() => exportExcel(summaries, results)}
        >
          ⬇ Export Excel
        </button>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <Th col="site">Site</Th>
              <Th col="foreseer_devices">Foreseer</Th>
              <Th col="linx_assets">LinX</Th>
              <Th col="active_types">Types</Th>
              <Th col="matched_types">Matched</Th>
              <Th col="needs_review">Needs Review</Th>
              <Th col="foreseer_only">Foreseer Only</Th>
              <Th col="linx_only">LinX Only</Th>
              <Th col="avg_score">Score</Th>
            </tr>
          </thead>
          <tbody>
            {filtered.map(s => (
              <tr
                key={s.site}
                style={{ cursor: 'pointer' }}
                onClick={() => drillSite(s.site)}
              >
                <td style={{ fontWeight: 600, color: 'var(--comcast-blue)' }}>{s.site}</td>
                <td style={{ textAlign: 'right' }}>{fmt(s.foreseer_devices)}</td>
                <td style={{ textAlign: 'right' }}>{fmt(s.linx_assets)}</td>
                <td style={{ textAlign: 'right' }}>{s.active_types}</td>
                <td style={{ textAlign: 'right', color: 'var(--green)' }}>{s.matched_types}</td>
                <td style={{ textAlign: 'right', color: s.needs_review > 0 ? 'var(--orange)' : 'inherit' }}>{s.needs_review}</td>
                <td style={{ textAlign: 'right', color: s.foreseer_only > 0 ? 'var(--yellow)' : 'inherit' }}>{s.foreseer_only}</td>
                <td style={{ textAlign: 'right', color: s.linx_only > 0 ? '#be185d' : 'inherit' }}>{s.linx_only}</td>
                <td>
                  {s.avg_score != null
                    ? <span className={scoreClass(s.avg_score)}>{s.avg_score}</span>
                    : '—'
                  }
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

async function exportExcel(summaries, results) {
  try {
    const res = await fetch('/api/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ results }),
    })
    if (!res.ok) throw new Error('Export failed')
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'GIG_Reconciliation_Results.xlsx'
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    alert('Export failed: ' + e.message)
  }
}

function EmptyState() {
  return (
    <div className="empty-state">
      <div className="icon">📋</div>
      <h3>No results yet</h3>
      <p>Upload files and run the reconciliation first.</p>
    </div>
  )
}
