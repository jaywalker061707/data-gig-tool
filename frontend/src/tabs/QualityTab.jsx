import React, { useMemo } from 'react'
import { useStore } from '../store'
import { activeRows } from '../utils'
import { BarChart, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer } from 'recharts'

export default function QualityTab() {
  const { results, activeSite } = useStore()
  const rows = activeRows(results?.[activeSite]?.reconciliation)

  const data = useMemo(() =>
    rows
      .filter(r => Number(r.linx_missing_serial_count) > 0 || Number(r.linx_missing_ip_count) > 0 || Number(r.foreseer_missing_ip_count) > 0)
      .sort((a, b) =>
        (Number(b.linx_missing_serial_count) + Number(b.linx_missing_ip_count) + Number(b.foreseer_missing_ip_count)) -
        (Number(a.linx_missing_serial_count) + Number(a.linx_missing_ip_count) + Number(a.foreseer_missing_ip_count))
      )
      .slice(0, 25)
      .map(r => ({
        type: r.device_type.length > 35 ? r.device_type.slice(0, 35) + '…' : r.device_type,
        'LinX Missing Serial':     Number(r.linx_missing_serial_count),
        'LinX Missing IP':         Number(r.linx_missing_ip_count),
        'Foreseer Missing IP':     Number(r.foreseer_missing_ip_count),
      }))
  , [rows])

  if (!results) return <div className="empty-state"><div className="icon">🔍</div><h3>No results yet</h3></div>

  if (!data.length) return (
    <div className="empty-state">
      <div className="icon">✅</div>
      <h3>No data quality issues found</h3>
      <p>All active device types have complete identifiers.</p>
    </div>
  )

  return (
    <div className="card">
      <div className="section-title" style={{ marginBottom: 4 }}>Missing Identifiers by Device Type</div>
      <div style={{ fontSize: 12, color: 'var(--gray-500)', marginBottom: 16 }}>Types with at least one missing serial or IP. Showing top 25.</div>
      <ResponsiveContainer width="100%" height={Math.max(data.length * 32, 300)}>
        <BarChart data={data} layout="vertical" margin={{ left: 8, right: 40 }}>
          <XAxis type="number" tick={{ fontSize: 11 }} />
          <YAxis type="category" dataKey="type" width={240} tick={{ fontSize: 10 }} />
          <Tooltip />
          <Legend />
          <Bar dataKey="LinX Missing Serial" fill="#dc2626" radius={[0, 3, 3, 0]} />
          <Bar dataKey="LinX Missing IP"     fill="#f97316" radius={[0, 3, 3, 0]} />
          <Bar dataKey="Foreseer Missing IP" fill="#7c3aed" radius={[0, 3, 3, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
