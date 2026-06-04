import React, { useMemo, useState } from 'react'
import { MapContainer, TileLayer, CircleMarker, GeoJSON, Popup, useMap } from 'react-leaflet'
import { useStore } from '../store'
import { siteSummary } from '../utils'
import 'leaflet/dist/leaflet.css'

// Score → color
function scoreColor(score) {
  if (score == null) return '#94a3b8'
  if (score >= 90) return '#16a34a'
  if (score >= 75) return '#65a30d'
  if (score >= 50) return '#ca8a04'
  if (score >= 25) return '#ea580c'
  return '#dc2626'
}

function regionColor(avg) {
  if (avg == null) return 'rgba(148,163,184,0.15)'
  if (avg >= 75) return 'rgba(22,163,74,0.12)'
  if (avg >= 50) return 'rgba(202,138,4,0.12)'
  if (avg >= 25) return 'rgba(234,88,12,0.12)'
  return 'rgba(220,38,38,0.12)'
}

function regionBorder(avg) {
  if (avg == null) return '#94a3b8'
  if (avg >= 75) return '#16a34a'
  if (avg >= 50) return '#ca8a04'
  if (avg >= 25) return '#ea580c'
  return '#dc2626'
}

// Compute avg score per region from results
function buildRegionScores(summaries, mapData) {
  const byRegion = {}
  const siteRegionMap = {}
  ;(mapData?.sites || []).forEach(s => { siteRegionMap[s.short_dns] = s.region })

  Object.values(summaries).forEach(s => {
    const region = siteRegionMap[s.site] || 'Unknown'
    if (!byRegion[region]) byRegion[region] = []
    if (s.avg_score != null) byRegion[region].push(s.avg_score)
  })

  const result = {}
  Object.entries(byRegion).forEach(([r, scores]) => {
    result[r] = scores.length ? Math.round(scores.reduce((a,b)=>a+b,0)/scores.length) : null
  })
  return result
}

export default function MapTab() {
  const { results, mapData, setActiveSite, setActiveTab } = useStore()
  const [selectedRegion, setSelectedRegion] = useState(null)

  const summaries = useMemo(() => {
    if (!results) return {}
    const m = {}
    Object.values(results).forEach(s => {
      const sum = siteSummary(s)
      m[sum.site] = sum
    })
    return m
  }, [results])

  const regionScores = useMemo(() =>
    buildRegionScores(summaries, mapData), [summaries, mapData])

  // Deduplicated sites list
  const sites = useMemo(() => {
    const seen = new Set()
    return (mapData?.sites || []).filter(s => {
      if (!s.lat || !s.lon) return false
      if (seen.has(s.short_dns)) return false
      seen.add(s.short_dns)
      return true
    })
  }, [mapData])

  const hasSites = sites.length > 0

  // Regional summary table
  const regionalRows = useMemo(() => {
    const byRegion = {}
    const siteRegionMap = {}
    ;(mapData?.sites || []).forEach(s => { siteRegionMap[s.short_dns] = s.region })

    Object.values(summaries).forEach(s => {
      const region = siteRegionMap[s.site] || 'Unknown'
      if (!byRegion[region]) byRegion[region] = { count: 0, scores: [], worst: null }
      byRegion[region].count++
      if (s.avg_score != null) {
        byRegion[region].scores.push({ site: s.site, score: s.avg_score })
      }
    })

    return Object.entries(byRegion).map(([region, d]) => {
      const scores = d.scores.map(x => x.score)
      const avg = scores.length ? Math.round(scores.reduce((a,b)=>a+b,0)/scores.length) : null
      const min = scores.length ? Math.min(...scores) : null
      const worst = d.scores.sort((a,b)=>a.score-b.score)[0]?.site || null
      return { region, count: d.count, avg, min, worst }
    }).sort((a,b) => (a.avg??999)-(b.avg??999))
  }, [summaries, mapData])

  const legend = [
    { label: '90–100', color: '#16a34a' },
    { label: '75–89',  color: '#65a30d' },
    { label: '50–74',  color: '#ca8a04' },
    { label: '25–49',  color: '#ea580c' },
    { label: '0–24',   color: '#dc2626' },
    { label: 'No data',color: '#94a3b8' },
  ]

  const regionCount = (mapData?.regions?.features?.length || 0)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, height: 'calc(100vh - 130px)' }}>

      {/* Info + legend bar */}
      <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap', flexShrink: 0 }}>
        <div style={{ fontSize: 12, color: 'var(--gray-500)' }}>
          {regionCount} regions · {sites.length} sites plotted
          {Object.keys(summaries).length > 0 && ` · ${Object.keys(summaries).length} with reconciliation data`}
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontSize: 11, color: 'var(--gray-400)', fontWeight: 600 }}>Score:</span>
          {legend.map(l => (
            <span key={l.label} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11 }}>
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: l.color, display: 'inline-block', flexShrink: 0 }} />
              <span style={{ color: 'var(--gray-600)' }}>{l.label}</span>
            </span>
          ))}
          <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11 }}>
            <span style={{ width: 10, height: 10, borderRadius: '50%', border: '2px solid #dc2626', display: 'inline-block', flexShrink: 0 }} />
            <span style={{ color: 'var(--gray-600)' }}>No Foreseer</span>
          </span>
        </div>
      </div>

      {/* Map */}
      <div style={{ flex: 1, minHeight: 480, borderRadius: 8, overflow: 'hidden', border: '1px solid var(--gray-200)', boxShadow: '0 1px 3px rgba(0,0,0,.08)' }}>
        {!hasSites && (
          <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f8fafc', flexDirection: 'column', gap: 8 }}>
            <div style={{ fontSize: 32 }}>🗺️</div>
            <div style={{ fontSize: 14, color: 'var(--gray-500)' }}>Run reconciliation to populate the map</div>
          </div>
        )}
        {hasSites && (
          <MapContainer
            center={[38.5, -96]}
            zoom={4}
            style={{ width: '100%', height: '100%' }}
            scrollWheelZoom={true}
          >
            <TileLayer
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              attribution='© OpenStreetMap contributors'
              opacity={0.65}
            />

            {/* Region hulls — color coded by avg score */}
            {(mapData?.regions?.features || []).map((feature, i) => {
              const regionName = feature.properties?.name
              const avg = regionScores[regionName]
              return (
                <GeoJSON
                  key={i}
                  data={feature}
                  style={{
                    fillColor:   regionColor(avg),
                    fillOpacity: 1,
                    color:       regionBorder(avg),
                    weight:      1.5,
                    opacity:     0.6,
                  }}
                  onEachFeature={(f, layer) => {
                    layer.bindTooltip(
                      `<strong>${regionName}</strong><br/>Avg score: ${avg ?? 'N/A'}`,
                      { sticky: true }
                    )
                  }}
                />
              )
            })}

            {/* Site markers */}
            {sites.map(site => {
              const sum     = summaries[site.short_dns]
              const score   = sum?.avg_score ?? null
              const color   = scoreColor(score)
              const hasData = !!sum
              const hasForeseer = site.has_foreseer !== false

              return (
                <CircleMarker
                  key={site.short_dns}
                  center={[site.lat, site.lon]}
                  radius={hasData ? 7 : 4}
                  pathOptions={{
                    fillColor:   hasForeseer ? color : 'transparent',
                    color:       hasForeseer ? color : '#dc2626',
                    weight:      hasForeseer ? 1 : 2,
                    fillOpacity: hasForeseer ? 0.85 : 0,
                    opacity:     1,
                  }}
                >
                  <Popup>
                    <div style={{ fontFamily: 'Segoe UI,sans-serif', minWidth: 180 }}>
                      <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 4 }}>{site.short_dns}</div>
                      <div style={{ fontSize: 11, color: '#64748b', marginBottom: 8 }}>{site.region || ''}</div>
                      {sum ? (
                        <>
                          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '3px 12px', fontSize: 12, marginBottom: 10 }}>
                            <div>Foreseer: <strong>{sum.foreseer_devices}</strong></div>
                            <div>LinX: <strong>{sum.linx_assets}</strong></div>
                            <div>Matched: <strong style={{ color: '#16a34a' }}>{sum.matched_types}</strong></div>
                            <div>Score: <strong style={{ color }}>{score ?? '—'}</strong></div>
                            <div>F-only: <strong style={{ color: '#ca8a04' }}>{sum.foreseer_only}</strong></div>
                            <div>L-only: <strong style={{ color: '#be185d' }}>{sum.linx_only}</strong></div>
                          </div>
                          <button
                            onClick={() => { setActiveSite(site.short_dns); setActiveTab('recon') }}
                            style={{ width: '100%', background: '#0061A0', color: 'white', border: 'none', borderRadius: 4, padding: '6px 0', cursor: 'pointer', fontSize: 12, fontWeight: 600 }}
                          >
                            View Reconciliation →
                          </button>
                        </>
                      ) : (
                        <div style={{ fontSize: 11, color: '#94a3b8' }}>No reconciliation data loaded</div>
                      )}
                    </div>
                  </Popup>
                </CircleMarker>
              )
            })}
          </MapContainer>
        )}
      </div>

      {/* Regional summary */}
      {regionalRows.length > 0 && (
        <div className="card" style={{ flexShrink: 0, maxHeight: 220, overflow: 'auto' }}>
          <div className="card-title">Regional Health Summary</div>
          <table>
            <thead>
              <tr>
                <th>Region</th>
                <th>Sites</th>
                <th>Avg Score</th>
                <th>Min Score</th>
                <th>Worst Site</th>
              </tr>
            </thead>
            <tbody>
              {regionalRows.map(r => (
                <tr key={r.region}
                  style={{ cursor: r.worst ? 'pointer' : 'default', background: selectedRegion === r.region ? 'var(--comcast-blue-light)' : '' }}
                  onClick={() => setSelectedRegion(r.region === selectedRegion ? null : r.region)}
                >
                  <td style={{ fontWeight: 600 }}>
                    <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: '50%', background: regionBorder(r.avg), marginRight: 8 }} />
                    {r.region}
                  </td>
                  <td>{r.count}</td>
                  <td><span className={`score-badge ${scoreCls(r.avg)}`}>{r.avg ?? '—'}</span></td>
                  <td><span className={`score-badge ${scoreCls(r.min)}`}>{r.min ?? '—'}</span></td>
                  <td style={{ fontSize: 12, color: 'var(--gray-500)', fontFamily: 'monospace' }}>{r.worst || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function scoreCls(s) {
  if (s == null) return ''
  if (s >= 90) return 's90'; if (s >= 75) return 's75'
  if (s >= 50) return 's50'; if (s >= 25) return 's25'
  return 's0'
}
