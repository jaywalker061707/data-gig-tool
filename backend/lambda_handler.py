"""
AWS Lambda handler for the GIG Data Integrity Tool.
Uses S3 for file storage and run persistence.
API Gateway triggers this function.
"""
import json, os, io, boto3, traceback, gzip, base64
from lambda_function import run_reconciliation, run_site_detail, load_msl
from map_data import build_map_data
from runs_store_s3 import save_run_s3, list_runs_s3, load_run_s3, apply_delta

s3      = boto3.client("s3")
BUCKET  = os.environ.get("S3_BUCKET", "gig-data-integrity-tool")
CORS    = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Methods": "GET,POST,DELETE,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
}


def lambda_handler(event, context):
    method = event.get("httpMethod", "GET")
    path   = event.get("path", "/")

    if method == "OPTIONS":
        return resp(200, {})

    try:
        if path == "/api/runs" and method == "GET":
            return resp(200, list_runs_s3(BUCKET))

        if path.startswith("/api/runs/") and method == "GET":
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

        if path == "/api/presign" and method == "POST":
            body = json.loads(event.get("body") or "{}")
            key  = f"uploads/{body['filename']}"
            url  = s3.generate_presigned_url(
                "put_object",
                Params={"Bucket": BUCKET, "Key": key, "ContentType": body.get("content_type", "application/octet-stream")},
                ExpiresIn=3600,
            )
            return resp(200, {"upload_url": url, "s3_key": key})

        if path == "/api/run" and method == "POST":
            return handle_run(event)

        if path == "/api/run-delta" and method == "POST":
            return handle_run_delta(event)

        if path == "/api/chat" and method == "POST":
            return handle_chat(event)

        return resp(404, {"error": f"No route for {method} {path}"})

    except Exception as e:
        print(traceback.format_exc())
        return resp(500, {"error": str(e)})


def handle_run(event):
    body = json.loads(event.get("body") or "{}")
    fb   = s3.get_object(Bucket=BUCKET, Key=body["foreseer_key"])["Body"].read()
    lb   = [s3.get_object(Bucket=BUCKET, Key=k)["Body"].read() for k in body["linx_keys"]]
    db   = s3.get_object(Bucket=BUCKET, Key=body["dict_key"])["Body"].read()
    name = body.get("run_name", "Reconciliation Run")
    dict_fn = body.get("dict_filename", "dictionary.csv")

    msl   = load_msl(fb)
    res   = run_reconciliation(fb, lb, db, msl, dict_fn)
    mdata = build_map_data(fb, res)
    rid   = save_run_s3(BUCKET, name, res, msl, mdata, run_type="full",
                         foreseer_bytes=fb, dict_bytes=db, dict_filename=dict_fn)

    return resp(200, {"status": "ok", "run_id": rid, "run_name": name,
                       "results": res, "msl_sites": msl, "map_data": mdata})


def handle_run_delta(event):
    body        = json.loads(event.get("body") or "{}")
    baseline_id = body.get("baseline_run_id")
    lb          = [s3.get_object(Bucket=BUCKET, Key=k)["Body"].read() for k in body["linx_keys"]]
    name        = body.get("run_name", "Delta Update")

    from runs_store_s3 import get_baseline_files_s3
    fb, db, dict_fn = get_baseline_files_s3(BUCKET, baseline_id)
    if not fb: return resp(400, {"error": "Baseline has no stored files. Run a Full Run first."})

    msl     = load_msl(fb)
    new_res = run_reconciliation(fb, lb, db, msl, dict_fn)
    changed = list(new_res.keys())
    merged_res, merged_msl, merged_map = apply_delta(baseline_id, new_res, msl, None, name, changed,
                                                      bucket=BUCKET)
    rid = save_run_s3(BUCKET, name, merged_res, merged_msl, merged_map,
                       run_type="delta", parent_run_id=baseline_id, changed_sites=changed)
    return resp(200, {"status": "ok", "run_id": rid, "run_name": name,
                       "changed_sites": changed, "results": merged_res,
                       "msl_sites": merged_msl, "map_data": merged_map})


def handle_chat(event):
    body    = json.loads(event.get("body") or "{}")
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return resp(200, {"reply": "AI chat requires ANTHROPIC_API_KEY in Lambda environment variables."})
    import anthropic
    r = anthropic.Anthropic(api_key=api_key).messages.create(
        model="claude-haiku-4-5-20251001", max_tokens=512,
        system=f"You are a data analyst for Comcast GIG. Be concise.\n\nContext:\n{body.get('context','')}",
        messages=[{"role": "user", "content": body.get("message", "")}],
    )
    return resp(200, {"reply": r.content[0].text})


def resp(status, body):
    return {
        "statusCode": status,
        "headers": {**CORS, "Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }
