import React, { useState, useRef, useEffect } from 'react'
import { useStore, setCachedFiles } from '../store'
import { runFull, runDelta } from '../api'

export default function UploadSidebar() {
  const { setResults, results, loadRuns, loadSavedRun,
          savedRuns, activeRunId, activeRunName, setActiveTab } = useStore()

  const [mode,       setMode]      = useState('full')   // 'full' | 'delta'
  const [foreseer,   setForeseer]  = useState(null)
  const [linxFiles,  setLinxFiles] = useState([])
  const [dictFile,   setDictFile]  = useState(null)
  const [runName,    setRunName]   = useState('')
  const [baselineId, setBaselineId]= useState('')
  const [status,     setStatus]    = useState(null)
  const [running,    setRunning]   = useState(false)
  const [showRuns,   setShowRuns]  = useState(false)

  const fRef = useRef(), lRef = useRef(), dRef = useRef()

  // Auto-load latest run on mount
  useEffect(() => {
    loadRuns().then(() => {
      loadSavedRun(null)
        .then(ok => { if (ok) setStatus({ type: 'success', msg: 'Latest run loaded.' }) })
    })
  }, [])

  // Set default baseline to latest full run when switching to delta mode
  useEffect(() => {
    if (mode === 'delta' && !baselineId) {
      const latest = savedRuns.find(r => r.run_type === 'full')
      if (latest) setBaselineId(latest.id)
    }
  }, [mode, savedRuns])

  const canRunFull  = !running && foreseer && linxFiles.length > 0 && dictFile
  const canRunDelta = !running && linxFiles.length > 0 && baselineId

  async function handleRun() {
    setRunning(true)
    const name = runName.trim() || defaultName(linxFiles, mode)
    setStatus({ type: 'info', msg: `Running "${name}"... this may take several minutes.` })
    try {
      const onStatus = msg => setStatus({ type: 'info', msg })
      let data
      if (mode === 'full') {
        data = await runFull(foreseer, linxFiles, dictFile, name, onStatus)
        setCachedFiles(foreseer, linxFiles, dictFile)
      } else {
        data = await runDelta(linxFiles, baselineId, name, onStatus)
      }
      setResults(data.results, data.msl_sites || [], data.map_data || null, data.run_id, data.run_name)

      const changed = data.changed_sites?.length
      const msg = mode === 'delta'
        ? `Delta saved. ${changed} site${changed !== 1 ? 's' : ''} updated: ${(data.changed_sites || []).slice(0,3).join(', ')}${changed > 3 ? '...' : ''}`
        : `Full run saved. ${Object.keys(data.results).length} sites processed.`
      setStatus({ type: 'success', msg })
      setRunName('')
      loadRuns()
    } catch (e) {
      setStatus({ type: 'error', msg: e.message })
    } finally {
      setRunning(false)
    }
  }

  async function handleLoadRun(runId) {
    setStatus({ type: 'info', msg: 'Loading...' })
    const ok = await loadSavedRun(runId)
    setShowRuns(false)
    setStatus(ok ? { type: 'success', msg: 'Run loaded.' } : { type: 'error', msg: 'Failed to load run.' })
  }

  async function handleDownload() {
    if (!results) return
    try {
      const res = await fetch(`${API_URL}/api/export`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ results }),
      })
      if (!res.ok) throw new Error('Export failed')
      const blob = await res.blob()
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      a.href = url
      a.download = `GIG_${(activeRunName || 'results').replace(/\s+/g, '_')}.xlsx`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) { alert('Export failed: ' + e.message) }
  }

  const fullRuns = savedRuns.filter(r => r.run_type === 'full')

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div className="sidebar-logo">GIG<span>tool</span></div>
        <div className="sidebar-subtitle">Data Integrity Platform</div>
      </div>

      {/* Mode toggle */}
      <div className="sidebar-section">
        <div className="sidebar-section-label">Run Type</div>
        <div style={{ display: 'flex', gap: 6 }}>
          {['full', 'delta'].map(m => (
            <button key={m} onClick={() => setMode(m)} style={{
              flex: 1, padding: '6px 0', borderRadius: 6, border: 'none',
              cursor: 'pointer', fontSize: 11, fontWeight: 600,
              background: mode === m ? 'var(--comcast-mid)' : 'rgba(255,255,255,.1)',
              color: mode === m ? 'white' : 'rgba(255,255,255,.5)',
            }}>
              {m === 'full' ? '⚡ Full Run' : '⚡ Update Sites'}
            </button>
          ))}
        </div>
        <div style={{ fontSize: 10, color: 'rgba(255,255,255,.35)', marginTop: 6, lineHeight: 1.5 }}>
          {mode === 'full'
            ? 'Upload all 3 files. Processes every site. Saves Foreseer + Dict for future updates.'
            : 'Upload only updated LinX file(s). Foreseer and Dictionary loaded from the baseline automatically.'}
        </div>
      </div>

      {/* File uploads */}
      <div className="sidebar-section">
        <div className="sidebar-section-label">Files</div>

        {/* Delta: pick baseline */}
        {mode === 'delta' && (
          <div style={{ marginBottom: 8 }}>
            <div style={{ fontSize: 10, color: 'rgba(255,255,255,.4)', marginBottom: 4 }}>Baseline run to update:</div>
            {fullRuns.length === 0 ? (
              <div style={{ fontSize: 11, color: '#f87171' }}>No full runs saved yet. Run a Full Run first.</div>
            ) : (
              <select
                value={baselineId}
                onChange={e => setBaselineId(e.target.value)}
                style={{
                  width: '100%', background: 'rgba(255,255,255,.1)', border: '1px solid rgba(255,255,255,.2)',
                  borderRadius: 6, padding: '6px 8px', fontSize: 11, color: 'white', outline: 'none',
                }}
              >
                {fullRuns.map(r => (
                  <option key={r.id} value={r.id} style={{ background: '#003a5e' }}>
                    {r.name} ({r.created_at?.slice(0,10)}, {r.sites_count} sites)
                  </option>
                ))}
              </select>
            )}
          </div>
        )}

        {/* Full run needs all 3 files */}
        {mode === 'full' && (
          <>
            <UploadZone label="Foreseer Export" hint=".xlsm — full multi-site export"
              accept=".xlsm,.xlsx" multiple={false} file={foreseer}
              inputRef={fRef} onChange={f => setForeseer(f[0])} />
            <UploadZone label="Asset Dictionary" hint=".csv or .xlsx"
              accept=".csv,.xlsx,.xlsm" multiple={false} file={dictFile}
              inputRef={dRef} onChange={f => setDictFile(f[0])} />
          </>
        )}

        {/* Both modes need LinX */}
        <UploadZone
          label={mode === 'delta' ? 'Updated LinX File(s)' : 'LinX Export(s)'}
          hint={mode === 'delta' ? 'Upload just the changed site(s)' : 'Full export or site-specific .xlsx'}
          accept=".xlsx" multiple={true} files={linxFiles}
          inputRef={lRef} onChange={setLinxFiles} />

        {/* Run name */}
        <input
          value={runName}
          onChange={e => setRunName(e.target.value)}
          placeholder="Name this run (optional)"
          style={{
            width: '100%', background: 'rgba(255,255,255,.08)',
            border: '1px solid rgba(255,255,255,.15)', borderRadius: 6,
            padding: '7px 10px', fontSize: 11, color: 'white', outline: 'none', marginTop: 6,
          }}
        />
      </div>

      {/* Actions */}
      <div className="sidebar-section">
        <button className="run-btn"
          onClick={handleRun}
          disabled={mode === 'full' ? !canRunFull : !canRunDelta}
        >
          {running ? <span className="spinner" /> : '▶'}
          {running ? 'Running...' : mode === 'full' ? 'Run Full Reconciliation' : 'Update Sites'}
        </button>
        <button className="download-btn" onClick={handleDownload} disabled={!results}
          style={{ marginTop: 6 }}>
          ⬇ Download Excel Results
        </button>
        {status && <div className={`status-box ${status.type}`}>{status.msg}</div>}
      </div>

      {/* Saved runs */}
      <div className="sidebar-section" style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <div className="sidebar-section-label">
          Saved Runs ({savedRuns.length})
          {savedRuns.length > 0 && (
            <button onClick={() => setShowRuns(s => !s)}
              style={{ float: 'right', background: 'none', border: 'none', color: 'rgba(255,255,255,.4)', fontSize: 10, cursor: 'pointer', textDecoration: 'underline' }}>
              {showRuns ? 'hide' : 'browse'}
            </button>
          )}
        </div>

        {activeRunName && (
          <div style={{ fontSize: 11, color: '#34d399', marginBottom: 4 }}>
            ▸ {activeRunName}
          </div>
        )}

        {savedRuns.length === 0 && (
          <div style={{ fontSize: 10, color: 'rgba(255,255,255,.3)', lineHeight: 1.6 }}>
            No saved runs yet.<br />Run a Full Reconciliation to create the first baseline.
          </div>
        )}

        {showRuns && savedRuns.length > 0 && (
          <div style={{ overflowY: 'auto', flex: 1, marginTop: 4 }}>
            {savedRuns.map(r => (
              <div key={r.id}
                onClick={() => handleLoadRun(r.id)}
                style={{
                  padding: '8px 10px', borderRadius: 5, cursor: 'pointer', marginBottom: 3,
                  background: r.id === activeRunId ? 'rgba(255,255,255,.15)' : 'rgba(255,255,255,.05)',
                  borderLeft: `3px solid ${r.run_type === 'delta' ? '#f59e0b' : '#0080cc'}`,
                }}
                onMouseEnter={e => { if (r.id !== activeRunId) e.currentTarget.style.background = 'rgba(255,255,255,.1)' }}
                onMouseLeave={e => { if (r.id !== activeRunId) e.currentTarget.style.background = 'rgba(255,255,255,.05)' }}
              >
                <div style={{ fontSize: 11, fontWeight: 600, color: 'rgba(255,255,255,.85)', marginBottom: 2 }}>
                  {r.run_type === 'delta' ? '↺ ' : '⚡ '}{r.name}
                </div>
                <div style={{ fontSize: 10, color: 'rgba(255,255,255,.4)' }}>
                  {r.created_at?.slice(0,10)} · {r.sites_count} sites · avg {r.avg_score ?? '—'}
                  {r.changed_sites?.length > 0 && r.run_type === 'delta' && (
                    <span style={{ color: '#f59e0b' }}> · {r.changed_sites.length} updated</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Nav */}
      <nav className="sidebar-nav">
        {[
          { id: 'map',     label: 'Site Map',        icon: '🗺️' },
          { id: 'batch',   label: 'Batch Summary',   icon: '📋' },
          { id: 'recon',   label: 'Reconciliation',  icon: '⚖️' },
          { id: 'status',  label: 'Status Overview', icon: '📊' },
          { id: 'count',   label: 'Count Comparison',icon: '📈' },
          { id: 'quality', label: 'Data Quality',    icon: '🔍' },
          { id: 'review',  label: 'Manual Review',   icon: '🔬' },
        ].map(t => <NavItem key={t.id} {...t} hasResults={!!results} />)}
      </nav>

      <div className="sidebar-footer">
        Comcast GIG Initiative<br />
        Foreseer ↔ LinX Reconciliation
      </div>
    </aside>
  )
}

function NavItem({ id, label, icon, hasResults }) {
  const { activeTab, setActiveTab } = useStore()
  const enabled = hasResults || id === 'map'
  return (
    <div className={`nav-item${activeTab === id ? ' active' : ''}${!enabled ? ' disabled' : ''}`}
      onClick={() => enabled && setActiveTab(id)}>
      <span className="nav-icon">{icon}</span>
      {label}
    </div>
  )
}

function UploadZone({ label, hint, accept, multiple, file, files, inputRef, onChange }) {
  const has = multiple ? (files?.length > 0) : !!file
  return (
    <div className={`sidebar-upload-zone${has ? ' filled' : ''}`}
      onDragOver={e => e.preventDefault()}
      onDrop={e => { e.preventDefault(); onChange(Array.from(e.dataTransfer.files)) }}
      onClick={() => inputRef.current?.click()}
    >
      <input ref={inputRef} type="file" accept={accept} multiple={multiple}
        style={{ display: 'none' }} onChange={e => onChange(Array.from(e.target.files))} />
      <div className="sidebar-upload-title">{has ? '✓ ' : ''}{label}</div>
      {!has && <div className="sidebar-upload-hint">{hint}</div>}
      {has && !multiple && <div className="sidebar-upload-name">{file.name}</div>}
      {has && multiple && files.map((f, i) => <div key={i} className="sidebar-upload-name">{f.name}</div>)}
    </div>
  )
}

function defaultName(linxFiles, mode) {
  const d    = new Date()
  const date = `${d.toLocaleString('default', { month: 'short' })} ${d.getDate()} ${d.getFullYear()}`
  const n    = linxFiles?.length || 0
  return mode === 'delta'
    ? `${date} — Update (${n} site${n !== 1 ? 's' : ''})`
    : `${date} — Full Run`
}
