/**
 * API layer — switches between local dev (multipart Flask) and
 * production (presigned S3 upload + Lambda JSON).
 */
const API_URL = import.meta.env.VITE_API_URL || ''
const IS_PROD = !!import.meta.env.VITE_API_URL

async function checkRes(res) {
  if (!res.ok) {
    const e = await res.json().catch(() => ({}))
    throw new Error(e.error || `Server error ${res.status}`)
  }
  return res.json()
}

async function uploadToS3(file) {
  const res = await fetch(`${API_URL}/api/presign`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename: file.name, content_type: file.type || 'application/octet-stream' }),
  })
  const { upload_url, s3_key } = await checkRes(res)
  await fetch(upload_url, {
    method: 'PUT',
    headers: { 'Content-Type': file.type || 'application/octet-stream' },
    body: file,
  })
  return s3_key
}

export async function runFull(foreseer, linxFiles, dict, runName, onStatus) {
  if (!IS_PROD) {
    onStatus('Processing...')
    const form = new FormData()
    form.append('foreseer', foreseer)
    linxFiles.forEach(f => form.append('linx', f))
    form.append('dict', dict)
    form.append('run_name', runName)
    return checkRes(await fetch('/api/run', { method: 'POST', body: form }))
  }

  onStatus('Uploading Foreseer...')
  const foreseerKey = await uploadToS3(foreseer)

  onStatus(`Uploading LinX file${linxFiles.length > 1 ? 's' : ''}...`)
  const linxKeys = []
  for (const f of linxFiles) {
    linxKeys.push(await uploadToS3(f))
  }

  onStatus('Uploading Dictionary...')
  const dictKey = await uploadToS3(dict)

  onStatus('Running reconciliation — please wait...')
  return checkRes(await fetch(`${API_URL}/api/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      foreseer_key: foreseerKey,
      linx_keys: linxKeys,
      dict_key: dictKey,
      dict_filename: dict.name,
      run_name: runName,
    }),
  }))
}

export async function runDelta(linxFiles, baselineRunId, runName, onStatus) {
  if (!IS_PROD) {
    onStatus('Processing delta...')
    const form = new FormData()
    linxFiles.forEach(f => form.append('linx', f))
    form.append('baseline_run_id', baselineRunId)
    form.append('run_name', runName)
    return checkRes(await fetch('/api/run-delta', { method: 'POST', body: form }))
  }

  onStatus('Uploading updated LinX file(s)...')
  const linxKeys = []
  for (const f of linxFiles) {
    linxKeys.push(await uploadToS3(f))
  }

  onStatus('Running delta reconciliation...')
  return checkRes(await fetch(`${API_URL}/api/run-delta`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ linx_keys: linxKeys, baseline_run_id: baselineRunId, run_name: runName }),
  }))
}
