import React, { useMemo } from 'react'
import { useStore } from '../store'
import { activeRows } from '../utils'
import { BarChart, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, Cell } from 'recharts'

const STATUS_COLORS = {
  'Match': '#16a34a',
  'Mismatch / Needs review': '#ea580c',
  'Present in Foreseer, Missing in LinX': '#ca8a04',
  'Present in LinX, Missing in Foreseer': '#be185d',
  'No records in either system': '#94a3b8',
}

export default function StatusTab() {
  const { results, activeSite } = useStore()
  const siteData = results?.[activeSite]
  const rows = activeRows(siteData?.reconciliation)

  const statusData = useMemo(() => {
    const counts = {}
    rows.forEach(r => { counts[r.match_status] = (counts[r.match_status] || 0) + 1 })
    return Object.entries(counts).map(([status, count]) => ({ status: shortLabel(status), full: status, count }))
      .sort((a, b) => b.count - a.count)
  }, [rows])

  const scoreData = useMemo(() => {
    const buckets = Array(10).fill(0)
    rows.forEach(r => {
      if (r.match_score != null) {
        const b = Math.min(9, Math.floor(Number(r.match_score) / 10))
        buckets[b]++
      }
    })
    return buckets.map((count, i) => ({ range: `${i*10}-${i*10+9}`, count }))
  }, [rows])

  if (!results) return <div className="empty-state"><div className="icon">📈</div><h3>No results yet</h3></div>

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
      <div className="card">
        <div className="section-title" style={{ marginBottom: 16 }}>Device Types by Match Status</div>
        <ResponsiveContainer width="100%" height={320}>
          <BarChart data={statusData} layout="vertical" margin={{ left: 8, right: 24 }}>
            <XAxis type="number" tick={{ fontSize: 11 }} />
            <YAxis type="category" dataKey="status" width={160} tick={{ fontSize: 11 }} />
            <Tooltip formatter={(v, n, p) => [v, p.payload.full]} />
            <Bar dataKey="count" radius={[0, 4, 4, 0]}>
              {statusData.map((entry, i) => (
                <Cell key={i} fill={STATUS_COLORS[entry.full] || '#64748b'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="card">
        <div className="section-title" style={{ marginBottom: 16 }}>Match Score Distribution</div>
        <ResponsiveContainer width="100%" height={320}>
          <BarChart data={scoreData} margin={{ left: 8, right: 24 }}>
            <XAxis dataKey="range" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip />
            <Bar dataKey="count" radius={[4, 4, 0, 0]}>
              {scoreData.map((entry, i) => (
                <Cell key={i} fill={scoreBucketColor(i)} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

function shortLabel(s) {
  const map = {
    'Match': 'Match',
    'Mismatch / Needs review': 'Mismatch',
    'Present in Foreseer, Missing in LinX': 'Foreseer Only',
    'Present in LinX, Missing in Foreseer': 'LinX Only',
    'No records in either system': 'No Records',
  }
  return map[s] || s
}

function scoreBucketColor(i) {
  if (i >= 9) return '#16a34a'
  if (i >= 7) return '#65a30d'
  if (i >= 5) return '#ca8a04'
  if (i >= 2) return '#ea580c'
  return '#dc2626'
}
