import React, { useState, useRef } from 'react'
import { useStore } from '../store'

const API_URL = import.meta.env.VITE_API_URL || ''

export default function UploadTab() {
  const { setResults, setActiveTab } = useStore()
  const [foreseer, setForeseer] = useState(null)
  const [linxFiles, setLinxFiles] = useState([])
  const [dictFile, setDictFile] = useState(null)
  const [status, setStatus] = useState(null)   // { type: 'info'|'success'|'error', msg }
  const [running, setRunning] = useState(false)

  const foreseerRef = useRef()
  const linxRef     = useRef()
  const dictRef     = useRef()

  const canRun = foreseer && linxFiles.length > 0 && dictFile && !running

  async function handleRun() {
    setRunning(true)
    setStatus({ type: 'info', msg: 'Processing files — this may take 20-60 seconds...' })
    try {
      const form = new FormData()
      form.append('foreseer', foreseer)
      linxFiles.forEach(f => form.append('linx', f))
      form.append('dict', dictFile)

      const res = await fetch(`${API_URL}/api/run`, { method: 'POST', body: form })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.error || `Server error ${res.status}`)
      }
      const data = await res.json()
      setResults(data.results, data.msl_sites || [])
      setStatus({ type: 'success', msg: `Done — ${Object.keys(data.results).length} site(s) processed.` })
    } catch (e) {
      setStatus({ type: 'error', msg: e.message })
    } finally {
      setRunning(false)
    }
  }

  return (
    <div>
      <div className="section-header">
        <div className="section-title">Upload Files</div>
      </div>

      <div className="upload-grid">
        <DropZone
          label="Foreseer Export"
          hint=".xlsm file — full multi-site export"
          accept=".xlsm,.xlsx"
          multiple={false}
          file={foreseer}
          inputRef={foreseerRef}
          onChange={f => setForeseer(f[0])}
        />
        <DropZone
          label="LinX Export(s)"
          hint="One or more .xlsx files — one per site"
          accept=".xlsx"
          multiple={true}
          files={linxFiles}
          inputRef={linxRef}
          onChange={setLinxFiles}
        />
        <DropZone
          label="Asset Type Dictionary"
          hint=".csv or .xlsx — device prefix mapping"
          accept=".csv,.xlsx,.xlsm"
          multiple={false}
          file={dictFile}
          inputRef={dictRef}
          onChange={f => setDictFile(f[0])}
        />
      </div>

      <button className="run-btn" onClick={handleRun} disabled={!canRun}>
        {running ? <span className="spinner" /> : '▶'}
        {running ? 'Running...' : 'Run Reconciliation'}
      </button>

      {status && (
        <div className={`status-bar ${status.type}`}>{status.msg}</div>
      )}

      <div style={{ marginTop: 32 }}>
        <div className="card" style={{ maxWidth: 560 }}>
          <div style={{ fontWeight: 700, marginBottom: 10, color: 'var(--gray-700)' }}>Instructions</div>
          <ol style={{ paddingLeft: 18, lineHeight: 2, color: 'var(--gray-500)', fontSize: 13 }}>
            <li>Upload the <strong>Foreseer</strong> .xlsm file (full company export)</li>
            <li>Upload one or more <strong>LinX</strong> .xlsx files — one per site you want to compare</li>
            <li>Upload the <strong>Asset Type Dictionary</strong> .csv</li>
            <li>Click <strong>Run Reconciliation</strong></li>
            <li>Explore results across the tabs above</li>
          </ol>
        </div>
      </div>
    </div>
  )
}

function DropZone({ label, hint, accept, multiple, file, files, inputRef, onChange }) {
  const hasFile = multiple ? (files && files.length > 0) : !!file

  function handleDrop(e) {
    e.preventDefault()
    const dropped = Array.from(e.dataTransfer.files)
    onChange(multiple ? dropped : dropped)
  }

  function handleChange(e) {
    const selected = Array.from(e.target.files)
    onChange(multiple ? selected : selected)
  }

  return (
    <div
      className={`upload-zone${hasFile ? ' has-file' : ''}`}
      onDragOver={e => e.preventDefault()}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={multiple}
        style={{ display: 'none' }}
        onChange={handleChange}
      />
      <div className="upload-icon">{hasFile ? '✅' : '📁'}</div>
      <div className="upload-label">{label}</div>
      <div className="upload-hint">{hint}</div>
      {!hasFile && <div className="upload-hint" style={{ marginTop: 8 }}>Click or drag & drop</div>}
      {hasFile && !multiple && <div className="upload-filename">{file.name}</div>}
      {hasFile && multiple && files.map((f, i) => (
        <div key={i} className="upload-filename">{f.name}</div>
      ))}
    </div>
  )
}
