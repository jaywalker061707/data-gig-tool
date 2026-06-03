export const STATUS = {
  'Match':                              'match',
  'Mismatch / Needs review':            'mismatch',
  'Present in Foreseer, Missing in LinX': 'foreseer',
  'Present in LinX, Missing in Foreseer': 'linx',
  'No records in either system':        'none',
}

export function rowClass(status) {
  return 'row-' + (STATUS[status] || 'none')
}

export function badgeClass(status) {
  return 'badge badge-' + (STATUS[status] || 'none')
}

export function scoreClass(score) {
  if (score == null) return ''
  if (score >= 90) return 'score-badge score-90'
  if (score >= 75) return 'score-badge score-75'
  if (score >= 50) return 'score-badge score-50'
  if (score >= 25) return 'score-badge score-25'
  return 'score-badge score-0'
}

export function fmt(v, decimals = 0) {
  if (v == null) return '—'
  return Number(v).toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

export function avg(arr, key) {
  const vals = arr.map(r => r[key]).filter(v => v != null && v !== '')
  if (!vals.length) return null
  return vals.reduce((a, b) => a + Number(b), 0) / vals.length
}

export function activeRows(recon) {
  return (recon || []).filter(r =>
    r.device_type !== 'TOTAL_ASSETS_ALL_TYPES' &&
    (Number(r.foreseer_count) > 0 || Number(r.linx_count) > 0)
  )
}

export function totalRow(recon) {
  return (recon || []).find(r => r.device_type === 'TOTAL_ASSETS_ALL_TYPES')
}

export function siteSummary(siteData) {
  const rows = activeRows(siteData.reconciliation)
  const total = totalRow(siteData.reconciliation)
  const scores = rows.map(r => Number(r.match_score)).filter(s => !isNaN(s))
  return {
    site: siteData.site_dns,
    foreseer_devices: total ? Number(total.foreseer_count) : 0,
    linx_assets:      total ? Number(total.linx_count) : 0,
    active_types:     rows.length,
    matched_types:    rows.filter(r => r.match_status === 'Match').length,
    needs_review:     rows.filter(r => r.match_status === 'Mismatch / Needs review').length,
    foreseer_only:    rows.filter(r => r.match_status === 'Present in Foreseer, Missing in LinX').length,
    linx_only:        rows.filter(r => r.match_status === 'Present in LinX, Missing in Foreseer').length,
    avg_score:        scores.length ? Math.round(scores.reduce((a,b) => a+b, 0) / scores.length) : null,
    lat:              siteData.msl_info?.lat,
    lon:              siteData.msl_info?.lon,
    region:           siteData.msl_info?.region,
  }
}
