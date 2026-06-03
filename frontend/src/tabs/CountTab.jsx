import React, { useMemo } from 'react'
import { useStore } from '../store'
import { activeRows } from '../utils'
import { BarChart, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer } from 'recharts'

export default function CountTab() {
  const { results, activeSite } = useStore()
  const rows = activeRows(results?.[activeSite]?.reconciliation)

  const data = useMemo(() =>
    [...rows]
      .sort((a, b) => Math.abs(Number(b.count_difference)) - Math.abs(Number(a.count_difference)))
      .slice(0, 30)
      .map(r => ({
        type: r.device_type.length > 35 ? r.device_type.slice(0, 35) + '…' : r.device_type,
        fullType: r.device_type,
        Foreseer: Number(r.foreseer_count),
        LinX: Number(r.linx_count),
      }))
  , [rows])

  if (!results) return <div className="empty-state"><div className="icon">📊</div><h3>No results yet</h3></div>

  return (
    <div className="card">
      <div className="section-title" style={{ marginBottom: 16 }}>Foreseer vs LinX Count by Device Type</div>
      <div style={{ fontSize: 12, color: 'var(--gray-500)', marginBottom: 16 }}>Sorted by largest count difference. Showing top 30 types.</div>
      <ResponsiveContainer width="100%" height={Math.max(data.length * 28, 300)}>
        <BarChart data={data} layout="vertical" margin={{ left: 8, right: 40 }}>
          <XAxis type="number" tick={{ fontSize: 11 }} />
          <YAxis type="category" dataKey="type" width={240} tick={{ fontSize: 10 }} />
          <Tooltip formatter={(v, n, p) => [v, n + ' — ' + p.payload.fullType]} />
          <Legend />
          <Bar dataKey="Foreseer" fill="#0061A0" radius={[0, 4, 4, 0]} />
          <Bar dataKey="LinX"     fill="#f97316" radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
