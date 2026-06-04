import { create } from 'zustand'

let _cachedFiles = null
export function setCachedFiles(foreseer, linxFiles, dict) {
  _cachedFiles = { foreseer, linxFiles, dict }
}
export function getCachedFiles() { return _cachedFiles }

export async function fetchSiteDetail(site_dns) {
  if (!_cachedFiles) return null
  const { foreseer, linxFiles, dict } = _cachedFiles
  if (!foreseer || !linxFiles || !dict) return null
  const form = new FormData()
  form.append('foreseer', foreseer)
  linxFiles.forEach(f => form.append('linx', f))
  form.append('dict', dict)
  form.append('site_dns', site_dns)
  const res = await fetch('/api/site-detail', { method: 'POST', body: form })
  if (!res.ok) return null
  return res.json()
}

export const useStore = create((set, get) => ({
  results:       null,
  mslSites:      [],
  mapData:       null,
  activeSite:    null,
  activeTab:     'map',
  loadingDetail: false,
  // Run management
  savedRuns:     [],
  activeRunId:   null,
  activeRunName: null,
  runsLoaded:    false,

  // Load list of saved runs from backend
  loadRuns: async () => {
    try {
      const res = await fetch('/api/runs')
      if (!res.ok) return
      const runs = await res.json()
      set({ savedRuns: runs, runsLoaded: true })
    } catch {}
  },

  // Load a specific saved run (or latest)
  loadSavedRun: async (runId) => {
    try {
      const url = runId ? `/api/runs/${runId}` : '/api/runs/latest'
      const res = await fetch(url)
      if (!res.ok) return false
      const run = await res.json()
      set({
        results:       run.results,
        mslSites:      run.msl_sites || [],
        mapData:       run.map_data  || null,
        activeSite:    Object.keys(run.results)[0] || null,
        activeTab:     'map',
        activeRunId:   run.id,
        activeRunName: run.name,
      })
      return true
    } catch { return false }
  },

  // Set results from a fresh reconciliation run
  setResults: (results, mslSites, mapData, runId, runName) => {
    const sites = Object.keys(results)
    set({
      results, mslSites, mapData,
      activeSite:    sites[0] || null,
      activeTab:     sites.length > 1 ? 'batch' : 'recon',
      activeRunId:   runId   || null,
      activeRunName: runName || null,
    })
  },

  setActiveSite: (site) => set({ activeSite: site }),
  setActiveTab:  (tab)  => set({ activeTab: tab }),
  setMapData:    (mapData) => set({ mapData }),

  // Load prefix trace + asset pairs for a site on demand
  loadSiteDetail: async (site_dns) => {
    const { results } = get()
    if (!results?.[site_dns]) return
    const existing = results[site_dns]
    if (existing.prefix_trace?.length > 0 || existing._detailLoaded) return
    if (get().loadingDetail) return
    set({ loadingDetail: true })
    try {
      const detail = await fetchSiteDetail(site_dns)
      if (detail) {
        set(state => ({
          results: {
            ...state.results,
            [site_dns]: {
              ...state.results[site_dns],
              prefix_trace:  detail.prefix_trace || [],
              asset_pairs:   detail.asset_pairs  || [],
              _detailLoaded: true,
            }
          }
        }))
      }
    } finally {
      set({ loadingDetail: false })
    }
  },
}))
