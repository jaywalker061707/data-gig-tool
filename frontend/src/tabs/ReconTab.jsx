import React, { useState, useMemo } from 'react'
import { useStore } from '../store'
import { activeRows, totalRow, fmt } from '../utils'
import SiteSearch from '../components/SiteSearch'

const STATUS = {
  'Match':                                'match',
  'Mismatch / Needs review':              'mismatch',
  'Present in Foreseer, Missing in LinX': 'foreseer',
  'Present in LinX, Missing in Foreseer': 'linx',
  'No records in either system':          'none',
}

function scoreClass(s) {
  if (s == null) return ''
  if (s >= 90) return 's90'; if (s >= 75) return 's75'
  if (s >= 50) return 's50'; if (s >= 25) return 's25'
  return 's0'
}

const SCORE_CHIPS = [
  { label: '90–100', min: 90,  max: 100, cls: 'chip-90' },
  { label: '75–89',  min: 75,  max: 89,  cls: 'chip-75' },
  { label: '50–74',  min: 50,  max: 74,  cls: 'chip-50' },
  { label: '25–49',  min: 25,  max: 49,  cls: 'chip-25' },
  { label: '0–24',   min: 0,   max: 24,  cls: 'chip-0'  },
]

export default function ReconTab() {
  const { results, activeSite, setActiveSite } = useStore()
  const [search,      setSearch]      = useState('')
  const [sort,        setSort]        = useState({ col: 'foreseer_count', dir: -1 })
  const [scoreFilter, setScoreFilter] = useState(null)

  const sites    = Object.keys(results || {})
  const siteData = results?.[activeSite]
  const recon    = siteData?.reconciliation || []
  const total    = totalRow(recon)
  const rows     = activeRows(recon)

  const filtered = useMemo(() => {
    let r = rows
    if (search) r = r.filter(x => x.device_type?.toLowerCase().includes(search.toLowerCase()))
    if (scoreFilter) r = r.filter(x => {
      const s = Number(x.match_score)
      return s >= scoreFilter.min && s <= scoreFilter.max
    })
    return [...r].sort((a, b) => {
      const av = a[sort.col] ?? '', bv = b[sort.col] ?? ''
      if (!isNaN(Number(av)) && !isNaN(Number(bv))) return (Number(av) - Number(bv)) * sort.dir
      return String(av).localeCompare(String(bv)) * sort.dir
    })
  }, [rows, search, sort, scoreFilter])

  const avgScore = useMemo(() => {
    const scores = rows.filter(r => r.foreseer_count > 0 || r.linx_count > 0).map(r => Number(r.match_score)).filter(s => !isNaN(s))
    return scores.length ? Math.round(scores.reduce((a,b)=>a+b,0)/scores.length) : null
  }, [rows])

  function Th({ col, label }) {
    const active = sort.col === col
    return (
      <th onClick={() => setSort(s => s.col === col ? { col, dir: -s.dir } : { col, dir: -1 })}>
        {label} {active ? (sort.dir === -1 ? '↓' : '↑') : ''}
      </th>
    )
  }

  if (!results) return <Empty />

  return (
    <div>
      {/* Site selector + search */}
      <div className="controls" style={{ marginBottom: 16 }}>
        <SiteSearch sites={sites} value={activeSite || ''} onChange={setActiveSite} placeholder="Select a site..." />
        <input className="search-input" placeholder="Search device type..." value={search} onChange={e => setSearch(e.target.value)} />
        {(search || scoreFilter) && (
          <button onClick={() => { setSearch(''); setScoreFilter(null) }}
            style={{ padding: '7px 12px', border: '1px solid var(--gray-300)', borderRadius: 6, cursor: 'pointer', fontSize: 12, background: 'white' }}>
            Clear filters
          </button>
        )}
      </div>

      {/* KPI cards */}
      <div className="kpi-row">
        <div className="kpi-card">
          <div className="kpi-label">Foreseer Devices</div>
          <div className="kpi-value" style={{ color: 'var(--comcast-blue)' }}>{fmt(total?.foreseer_count)}</div>
          <div className="kpi-sub">unique devices at site</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">LinX Assets</div>
          <div className="kpi-value" style={{ color: '#0d9488' }}>{fmt(total?.linx_count)}</div>
          <div className="kpi-sub">after project filter</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Types Matched</div>
          <div className="kpi-value" style={{ color: 'var(--green)' }}>{rows.filter(r=>r.match_status==='Match').length}</div>
          <div className="kpi-sub">of {rows.filter(r=>r.foreseer_count>0||r.linx_count>0).length} active types</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Avg Match Score</div>
          <div className="kpi-value" style={{ color: avgScore >= 75 ? 'var(--green)' : avgScore >= 50 ? 'var(--yellow)' : 'var(--red)' }}>
            {avgScore ?? '—'}
          </div>
          <div className="kpi-sub">0 – 100 scale</div>
        </div>
      </div>

      {/* Score filter chips */}
      <div className="score-chips">
        <span style={{ fontSize: 11, color: 'var(--gray-500)', fontWeight: 600 }}>Filter by score:</span>
        <button className={`score-chip chip-all${!scoreFilter ? ' active' : ''}`}
          onClick={() => setScoreFilter(null)}>All</button>
        {SCORE_CHIPS.map(c => (
          <button key={c.label}
            className={`score-chip ${c.cls}${scoreFilter?.label === c.label ? ' active' : ''}`}
            onClick={() => setScoreFilter(f => f?.label === c.label ? null : c)}>
            {c.label}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <Th col="device_type"           label="Device Type" />
              <Th col="foreseer_count"         label="Foreseer" />
              <Th col="linx_count"             label="LinX" />
              <Th col="count_difference"       label="Diff" />
              <Th col="pct_difference"         label="%" />
              <Th col="match_status"           label="Status" />
              <Th col="match_score"            label="Score" />
              <th>Notes</th>
              <th>Missing SN (L)</th>
              <th>Missing IP (F/L)</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((row, i) => {
              const cls = 'row-' + (STATUS[row.match_status] || 'none')
              const fc = Number(row.foreseer_count), lc = Number(row.linx_count)
              return (
                <tr key={i} className={cls}>
                  <td style={{ fontWeight: 600, maxWidth: 260 }}>{row.device_type}</td>
                  <td style={{ textAlign: 'right', fontWeight: fc > 0 ? 600 : 400 }}>{fc || '—'}</td>
                  <td style={{ textAlign: 'right', fontWeight: lc > 0 ? 600 : 400 }}>{lc || '—'}</td>
                  <td style={{ textAlign: 'right', color: Number(row.count_difference) !== 0 ? 'var(--orange)' : 'var(--gray-400)', fontWeight: 600 }}>
                    {Number(row.count_difference) > 0 ? '+' : ''}{fmt(row.count_difference)}
                  </td>
                  <td style={{ textAlign: 'right', color: 'var(--gray-500)' }}>
                    {row.pct_difference != null ? fmt(row.pct_difference, 1) + '%' : '—'}
                  </td>
                  <td>
                    <span className={`badge badge-${STATUS[row.match_status] || 'none'}`}>
                      {row.match_status?.replace('Present in ','').replace(', Missing in',' →') || '—'}
                    </span>
                  </td>
                  <td style={{ textAlign: 'center' }}>
                    {row.match_score != null
                      ? <span className={`score-badge ${scoreClass(Number(row.match_score))}`}>{row.match_score}</span>
                      : '—'}
                  </td>
                  <td style={{ fontSize: 11, color: 'var(--gray-500)', maxWidth: 280, whiteSpace: 'normal' }}>{row.notes || '—'}</td>
                  <td style={{ textAlign: 'right' }}>
                    {row.linx_missing_serial_count > 0
                      ? <span style={{ color: 'var(--red)', fontWeight: 600 }}>{row.linx_missing_serial_count}</span>
                      : <span style={{ color: 'var(--gray-300)' }}>—</span>}
                  </td>
                  <td style={{ textAlign: 'right', fontSize: 12 }}>
                    {(Number(row.foreseer_missing_ip_count) + Number(row.linx_missing_ip_count)) > 0
                      ? <span style={{ color: 'var(--orange)' }}>F:{row.foreseer_missing_ip_count} L:{row.linx_missing_ip_count}</span>
                      : <span style={{ color: 'var(--gray-300)' }}>—</span>}
                  </td>
                </tr>
              )
            })}
            {total && (
              <tr className="total-row">
                <td>TOTAL</td>
                <td style={{ textAlign:'right' }}>{fmt(total.foreseer_count)}</td>
                <td style={{ textAlign:'right' }}>{fmt(total.linx_count)}</td>
                <td style={{ textAlign:'right' }}>{fmt(total.count_difference)}</td>
                <td style={{ textAlign:'right' }}>{fmt(total.pct_difference, 1)}%</td>
                <td colSpan={5} />
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div style={{ marginTop: 8, fontSize: 11, color: 'var(--gray-400)' }}>
        Showing {filtered.length} of {rows.length} device types
        {siteData?.sanity && ` · Raw: Foreseer ${siteData.sanity.foreseer_raw_rows} rows, LinX ${siteData.sanity.linx_raw_rows} rows (${siteData.sanity.linx_after_project_filter} after project filter)`}
      </div>
    </div>
  )
}

function Empty() {
  return <div className="empty-state"><div className="icon">⚖️</div><h3>No results yet</h3><p>Upload files and run the reconciliation first.</p></div>
}
