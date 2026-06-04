"""
AWS Lambda handler — GIG Data Integrity Tool
Async job pattern:
  POST /api/run      → queues job, returns {job_id} immediately
  GET  /api/jobs/ID  → returns {status, progress} or full result when done
  Background invoke  → does the actual processing, writes result to S3
"""
import json, os, io, uuid, boto3, traceback, gzip
from datetime import datetime

s3_client  = boto3.client("s3")
lam_client = boto3.client("lambda")
BUCKET     = os.environ.get("S3_BUCKET", "gig-data-integrity-tool")
FUNC_NAME  = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "gig-comparison-engine")


def lambda_handler(event, context):
    # ── Background processing invocation (no HTTP context) ──────────────────
    if event.get("_gig_action") == "process":
        return _process_job(event)

    # ── HTTP request ─────────────────────────────────────────────────────────
    method = (event.get("httpMethod")
              or event.get("requestContext", {}).get("http", {}).get("method", "GET"))
    path   = event.get("rawPath") or event.get("path", "/")

    if method == "OPTIONS":
        return resp(200, {})

    try:
        # Saved runs list
        if path == "/api/runs" and method == "GET":
            from runs_store_s3 import list_runs_s3
            return resp(200, list_runs_s3(BUCKET))

        # Load a specific / latest run
        if path.startswith("/api/runs/") and method == "GET":
            from runs_store_s3 import list_runs_s3, load_run_s3
            run_id = path.split("/api/runs/")[1]
            if run_id == "latest":
                runs = list_runs_s3(BUCKET)
                if not runs: return resp(404, {"error": "No saved runs"})
                run = load_run_s3(BUCKET, runs[0]["id"])
            else:
                run = load_run_s3(BUCKET, run_id)
            if not run: return resp(404, {"error": "Run not found"})
            run.pop("foreseer_b64", None); run.pop("dict_b64", None)
            return resp(200, run)

        # Presigned URL for direct S3 upload from browser
        if path == "/api/presign" and method == "POST":
            body = json.loads(event.get("body") or "{}")
            key  = f"uploads/{body['filename']}"
            url  = s3_client.generate_presigned_url(
                "put_object",
                Params={"Bucket": BUCKET, "Key": key,
                        "ContentType": body.get("content_type", "application/octet-stream")},
                ExpiresIn=3600,
            )
            return resp(200, {"upload_url": url, "s3_key": key})

        # Start a new full reconciliation run (async)
        if path == "/api/run" and method == "POST":
            return _queue_run(event)

        # Start a delta run (async)
        if path == "/api/run-delta" and method == "POST":
            return _queue_delta(event)

        # Poll job status / get result
        if path.startswith("/api/jobs/") and method == "GET":
            job_id = path.split("/api/jobs/")[1]
            return _get_job(job_id)

        # AI chat
        if path == "/api/chat" and method == "POST":
            return _handle_chat(event)

        return resp(404, {"error": f"No route for {method} {path}"})

    except Exception as e:
        print(traceback.format_exc())
        return resp(500, {"error": str(e)})


# ── Job queueing ─────────────────────────────────────────────────────────────

def _queue_run(event):
    body     = json.loads(event.get("body") or "{}")
    job_id   = str(uuid.uuid4())
    run_name = body.get("run_name") or _default_name(body.get("linx_keys", []))

    # Write job request to S3
    _write_job_status(job_id, "queued", {"run_name": run_name, "type": "full", **body})

    # Invoke self asynchronously — Lambda returns immediately, processing runs in background
    lam_client.invoke(
        FunctionName=FUNC_NAME,
        InvocationType="Event",   # async — no waiting for response
        Payload=json.dumps({
            "_gig_action":  "process",
            "job_id":       job_id,
            "run_type":     "full",
            "run_name":     run_name,
            "foreseer_key": body.get("foreseer_key"),
            "linx_keys":    body.get("linx_keys", []),
            "dict_key":     body.get("dict_key"),
            "dict_filename":body.get("dict_filename", "dictionary.csv"),
        }),
    )
    return resp(202, {"job_id": job_id, "run_name": run_name,
                       "message": "Processing started. Poll /api/jobs/{job_id} for status."})


def _queue_delta(event):
    body        = json.loads(event.get("body") or "{}")
    job_id      = str(uuid.uuid4())
    baseline_id = body.get("baseline_run_id")
    run_name    = body.get("run_name") or "Delta Update"

    _write_job_status(job_id, "queued", {"run_name": run_name, "type": "delta", **body})

    lam_client.invoke(
        FunctionName=FUNC_NAME,
        InvocationType="Event",
        Payload=json.dumps({
            "_gig_action":    "process",
            "job_id":         job_id,
            "run_type":       "delta",
            "run_name":       run_name,
            "baseline_run_id":baseline_id,
            "linx_keys":      body.get("linx_keys", []),
        }),
    )
    return resp(202, {"job_id": job_id, "run_name": run_name,
                       "message": "Delta processing started."})


def _get_job(job_id):
    """Return job status. If complete, return full result."""
    try:
        obj = s3_client.get_object(Bucket=BUCKET, Key=f"jobs/{job_id}/status.json")
        status = json.loads(obj["Body"].read())
    except s3_client.exceptions.NoSuchKey:
        return resp(404, {"error": "Job not found"})

    if status.get("state") == "complete":
        # Load full result
        try:
            obj = s3_client.get_object(Bucket=BUCKET, Key=f"jobs/{job_id}/result.json.gz")
            with gzip.open(io.BytesIO(obj["Body"].read()), "rt") as f:
                result = json.load(f)
            result.pop("foreseer_b64", None); result.pop("dict_b64", None)
            return resp(200, {"state": "complete", **result})
        except Exception as e:
            return resp(500, {"error": f"Result load failed: {e}"})

    return resp(200, status)


# ── Background processing ─────────────────────────────────────────────────────

def _process_job(event):
    job_id   = event["job_id"]
    run_type = event.get("run_type", "full")

    try:
        _write_job_status(job_id, "processing", {"message": "Loading files..."})

        from lambda_function import run_reconciliation, load_msl
        from map_data import build_map_data
        from runs_store_s3 import save_run_s3, get_baseline_files_s3, apply_delta

        if run_type == "full":
            fb = _read_s3(event["foreseer_key"])
            lb = [_read_s3(k) for k in event["linx_keys"]]
            db = _read_s3(event["dict_key"])
            dict_fn  = event.get("dict_filename", "dictionary.csv")
            run_name = event["run_name"]

            _write_job_status(job_id, "processing", {"message": f"Running reconciliation..."})
            msl      = load_msl(fb)
            results  = run_reconciliation(fb, lb, db, msl, dict_fn)
            map_data = build_map_data(fb, results)

            run_id = save_run_s3(BUCKET, run_name, results, msl, map_data,
                                  run_type="full", foreseer_bytes=fb,
                                  dict_bytes=db, dict_filename=dict_fn)

        else:  # delta
            baseline_id = event["baseline_run_id"]
            lb = [_read_s3(k) for k in event["linx_keys"]]
            run_name = event["run_name"]

            fb, db, dict_fn = get_baseline_files_s3(BUCKET, baseline_id)
            if not fb:
                raise ValueError("Baseline has no stored files. Run a Full Run first.")

            msl      = load_msl(fb)
            new_res  = run_reconciliation(fb, lb, db, msl, dict_fn)
            changed  = list(new_res.keys())
            merged, merged_msl, merged_map = apply_delta(
                baseline_id, new_res, msl, None, run_name, changed, bucket=BUCKET)

            run_id = save_run_s3(BUCKET, run_name, merged, merged_msl, merged_map,
                                  run_type="delta", parent_run_id=baseline_id,
                                  changed_sites=changed)
            results  = merged
            map_data = merged_map

        # Write result to S3
        payload = {
            "run_id": run_id, "run_name": run_name,
            "results": results, "msl_sites": msl, "map_data": map_data,
        }
        buf = io.BytesIO()
        with gzip.open(buf, "wt") as f:
            json.dump(payload, f, default=str)
        buf.seek(0)
        s3_client.put_object(Bucket=BUCKET, Key=f"jobs/{job_id}/result.json.gz",
                              Body=buf.read())

        _write_job_status(job_id, "complete", {
            "run_id": run_id, "run_name": run_name,
            "sites_count": len(results),
        })

    except Exception as e:
        print(traceback.format_exc())
        _write_job_status(job_id, "error", {"message": str(e)})


# ── Chat ──────────────────────────────────────────────────────────────────────

def _handle_chat(event):
    body    = json.loads(event.get("body") or "{}")
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return resp(200, {"reply": "AI chat requires ANTHROPIC_API_KEY in Lambda environment."})
    import anthropic
    r = anthropic.Anthropic(api_key=api_key).messages.create(
        model="claude-haiku-4-5-20251001", max_tokens=512,
        system=f"You are a GIG Data Integrity analyst. Be concise.\n\nContext:\n{body.get('context','')}",
        messages=[{"role": "user", "content": body.get("message", "")}],
    )
    return resp(200, {"reply": r.content[0].text})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _read_s3(key):
    return s3_client.get_object(Bucket=BUCKET, Key=key)["Body"].read()


def _write_job_status(job_id, state, extra=None):
    status = {"job_id": job_id, "state": state,
              "updated_at": datetime.now().isoformat(), **(extra or {})}
    s3_client.put_object(Bucket=BUCKET, Key=f"jobs/{job_id}/status.json",
                          Body=json.dumps(status), ContentType="application/json")


def _default_name(linx_keys):
    d = datetime.now()
    n = len(linx_keys)
    return f"{d.strftime('%b %d %Y')} — {n} LinX file{'s' if n != 1 else ''}"


def resp(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }
