/**
 * API layer — async job pattern
 * 1. Upload files to S3 via presigned URLs
 * 2. Trigger Lambda (returns job_id immediately)
 * 3. Poll /api/jobs/{job_id} every 10s until complete
 */
const API_URL = import.meta.env.VITE_API_URL || ''

async function checkRes(res) {
  if (!res.ok) {
    const e = await res.json().catch(() => ({}))
    throw new Error(e.error || `Server error ${res.status}`)
  }
  return res.json()
}

async function uploadToS3(file, onStatus) {
  onStatus(`Uploading ${file.name}...`)
  const { upload_url, s3_key } = await checkRes(
    await fetch(`${API_URL}/api/presign`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: file.name, content_type: file.type || 'application/octet-stream' }),
    })
  )
  const putRes = await fetch(upload_url, {
    method: 'PUT',
    headers: { 'Content-Type': file.type || 'application/octet-stream' },
    body: file,
  })
  if (!putRes.ok) throw new Error(`S3 upload failed: ${putRes.status}`)
  return s3_key
}

async function pollJob(jobId, onStatus) {
  const MAX_POLLS = 180  // 30 minutes max
  for (let i = 0; i < MAX_POLLS; i++) {
    await new Promise(r => setTimeout(r, 10000))  // wait 10 seconds
    const data = await checkRes(await fetch(`${API_URL}/api/jobs/${jobId}`))

    if (data.state === 'complete') return data
    if (data.state === 'error') throw new Error(data.message || 'Processing failed')

    const elapsed = Math.round((i + 1) * 10 / 60)
    onStatus(`Processing... ${elapsed} min elapsed. Results will load automatically when done.`)
  }
  throw new Error('Timed out waiting for results')
}

export async function runFull(foreseer, linxFiles, dict, runName, onStatus) {
  // EC2 / local dev: direct multipart POST, no S3 presign needed
  if (!IS_PROD) {
    onStatus('Uploading and processing... this may take several minutes.')
    const form = new FormData()
    form.append('foreseer', foreseer)
    linxFiles.forEach(f => form.append('linx', f))
    form.append('dict', dict)
    form.append('run_name', runName)
    return checkRes(await fetch('/api/run', { method: 'POST', body: form }))
  }

  // Lambda: upload to S3 first, then trigger async job
  onStatus('Uploading Foreseer file...')
  const foreseerKey = await uploadToS3(foreseer, onStatus)

  const linxKeys = []
  for (const f of linxFiles) {
    linxKeys.push(await uploadToS3(f, onStatus))
  }

  onStatus('Uploading Asset Dictionary...')
  const dictKey = await uploadToS3(dict, onStatus)

  // Start async job — returns immediately with job_id
  onStatus('Starting reconciliation...')
  const { job_id, run_name } = await checkRes(
    await fetch(`${API_URL}/api/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        foreseer_key: foreseerKey,
        linx_keys: linxKeys,
        dict_key: dictKey,
        dict_filename: dict.name,
        run_name: runName,
      }),
    })
  )

  onStatus(`Job started (${run_name}). Processing 1,800+ sites — check back in ~10 minutes. This page will update automatically.`)

  // Poll until done
  return await pollJob(job_id, onStatus)
}

export async function runDelta(linxFiles, baselineRunId, runName, onStatus) {
  const linxKeys = []
  for (const f of linxFiles) {
    linxKeys.push(await uploadToS3(f, onStatus))
  }

  onStatus('Starting delta update...')
  const { job_id } = await checkRes(
    await fetch(`${API_URL}/api/run-delta`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ linx_keys: linxKeys, baseline_run_id: baselineRunId, run_name: runName }),
    })
  )

  return await pollJob(job_id, onStatus)
}
