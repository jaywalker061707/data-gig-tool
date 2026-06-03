"""
S3-backed run storage — mirrors runs_store.py but uses S3 instead of local disk.
Run metadata index stored at s3://BUCKET/runs/index.json
Each run stored at s3://BUCKET/runs/{run_id}.json.gz
"""
import json, gzip, io, re, base64, boto3
from datetime import datetime

INDEX_KEY = "runs/index.json"


def _s3():
    return boto3.client("s3")


def _slug(name):
    return re.sub(r'[^a-zA-Z0-9_\-]', '_', name.strip())[:40]


def _summary_stats(results):
    scores = []
    for s in results.values():
        for r in s.get("reconciliation", []):
            if (r.get("device_type") != "TOTAL_ASSETS_ALL_TYPES"
                    and r.get("match_score") is not None
                    and ((r.get("foreseer_count") or 0) > 0 or (r.get("linx_count") or 0) > 0)):
                scores.append(float(r["match_score"]))
    return round(sum(scores) / len(scores), 1) if scores else None


def save_run_s3(bucket, name, results, msl_sites, map_data,
                run_type="full", parent_run_id=None,
                foreseer_bytes=None, dict_bytes=None, dict_filename=None,
                changed_sites=None):
    s3c = _s3()
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    rid = f"{ts}_{_slug(name)}"

    payload = {
        "id":            rid,
        "name":          name,
        "run_type":      run_type,
        "parent_run_id": parent_run_id,
        "created_at":    datetime.now().isoformat(),
        "sites_count":   len(results),
        "avg_score":     _summary_stats(results),
        "changed_sites": changed_sites or list(results.keys()),
        "results":       results,
        "msl_sites":     msl_sites,
        "map_data":      map_data,
        "foreseer_b64":  base64.b64encode(foreseer_bytes).decode() if foreseer_bytes and run_type == "full" else None,
        "dict_b64":      base64.b64encode(dict_bytes).decode()     if dict_bytes     and run_type == "full" else None,
        "dict_filename": dict_filename if run_type == "full" else None,
    }

    # Save full run as gzipped JSON
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="w") as f:
        f.write(json.dumps(payload, default=str).encode())
    buf.seek(0)
    s3c.put_object(Bucket=bucket, Key=f"runs/{rid}.json.gz",
                   Body=buf.read(), ContentType="application/gzip")

    # Update index
    meta = {
        "id": rid, "name": name, "run_type": run_type,
        "parent_run_id": parent_run_id,
        "created_at": payload["created_at"],
        "sites_count": payload["sites_count"],
        "avg_score": payload["avg_score"],
        "changed_sites": payload["changed_sites"],
    }
    index = _load_index(bucket)
    index.insert(0, meta)
    s3c.put_object(Bucket=bucket, Key=INDEX_KEY,
                   Body=json.dumps(index).encode(), ContentType="application/json")
    print(f"S3 run saved: {rid}")
    return rid


def list_runs_s3(bucket):
    return _load_index(bucket)


def load_run_s3(bucket, run_id):
    try:
        obj = _s3().get_object(Bucket=bucket, Key=f"runs/{run_id}.json.gz")
        with gzip.GzipFile(fileobj=io.BytesIO(obj["Body"].read())) as f:
            return json.loads(f.read())
    except Exception as e:
        print(f"Could not load run {run_id}: {e}")
        return None


def get_baseline_files_s3(bucket, run_id):
    run = load_run_s3(bucket, run_id)
    if not run:
        return None, None, None
    fb  = base64.b64decode(run["foreseer_b64"]) if run.get("foreseer_b64") else None
    db  = base64.b64decode(run["dict_b64"])     if run.get("dict_b64")     else None
    dfn = run.get("dict_filename", "dictionary.csv")
    return fb, db, dfn


def apply_delta(baseline_id, new_results, msl_sites, map_data, run_name, changed_sites, bucket=None):
    baseline = load_run_s3(bucket, baseline_id) if bucket else None
    if not baseline:
        return new_results, msl_sites, map_data

    merged = dict(baseline["results"])
    for site, data in new_results.items():
        from runs_store import _site_avg_score
        data["_delta"] = {
            "updated_at":       datetime.now().isoformat(),
            "parent_run_id":    baseline_id,
            "parent_run_name":  baseline.get("name"),
            "prev_avg_score":   _site_avg_score(baseline["results"].get(site, {})),
            "new_avg_score":    _site_avg_score(data),
        }
        merged[site] = data

    from utils_map import score_sites
    merged_map = score_sites(baseline.get("map_data"), merged)
    return merged, baseline.get("msl_sites", msl_sites), merged_map


def _load_index(bucket):
    try:
        obj = _s3().get_object(Bucket=bucket, Key=INDEX_KEY)
        return json.loads(obj["Body"].read())
    except:
        return []
