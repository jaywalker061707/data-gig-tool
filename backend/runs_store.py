"""
Named runs storage.
Supports two run types:
  - full:  all sites processed, Foreseer + Dict bytes stored for future deltas
  - delta: one or more sites re-processed, merged on top of a parent baseline run
"""
import os, json, gzip, re, io
from datetime import datetime

RUNS_DIR = os.path.join(os.path.dirname(__file__), "data", "runs")


def _ensure():
    os.makedirs(RUNS_DIR, exist_ok=True)


def _slug(name):
    return re.sub(r'[^a-zA-Z0-9_\-]', '_', name.strip())[:40]


def _path(run_id):
    return os.path.join(RUNS_DIR, f"{run_id}.json.gz")


def _summary_stats(results):
    scores = []
    for s in results.values():
        for r in s.get("reconciliation", []):
            if (r.get("device_type") != "TOTAL_ASSETS_ALL_TYPES"
                    and r.get("match_score") is not None
                    and ((r.get("foreseer_count") or 0) > 0 or (r.get("linx_count") or 0) > 0)):
                scores.append(float(r["match_score"]))
    return round(sum(scores) / len(scores), 1) if scores else None


# ── Save ──────────────────────────────────────────────────────────────────

def save_run(name, results, msl_sites, map_data,
             run_type="full", parent_run_id=None,
             foreseer_bytes=None, dict_bytes=None, dict_filename=None,
             changed_sites=None):
    """
    Save a run to disk.

    run_type: "full" or "delta"
    parent_run_id: for delta runs — which baseline this extends
    foreseer_bytes / dict_bytes: stored in full runs for reuse in deltas
    changed_sites: list of site dns strings that changed (delta runs)
    """
    _ensure()
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
        # Store source files in full runs so deltas can reuse them
        "foreseer_b64":  _b64(foreseer_bytes) if foreseer_bytes and run_type == "full" else None,
        "dict_b64":      _b64(dict_bytes)     if dict_bytes     and run_type == "full" else None,
        "dict_filename": dict_filename        if run_type == "full" else None,
    }

    with gzip.open(_path(rid), "wt", encoding="utf-8") as f:
        json.dump(payload, f, default=str)

    print(f"Run saved: {rid} ({len(results)} sites, avg {payload['avg_score']}, type={run_type})")
    return rid


# ── Delta merge ───────────────────────────────────────────────────────────

def apply_delta(baseline_run_id, new_results, new_msl_sites, new_map_data,
                run_name, changed_sites):
    """
    Merge new_results (a few sites) into a baseline run.
    Returns (merged_results, merged_msl_sites, merged_map_data)
    """
    baseline = load_run(baseline_run_id)
    if not baseline:
        raise ValueError(f"Baseline run {baseline_run_id} not found")

    # Merge: start from baseline, override with new site results
    merged_results = dict(baseline["results"])
    for site, data in new_results.items():
        # Tag the updated site so UI can highlight it
        data["_delta"] = {
            "updated_at":    datetime.now().isoformat(),
            "parent_run_id": baseline_run_id,
            "parent_run_name": baseline.get("name"),
            "prev_avg_score": _site_avg_score(baseline["results"].get(site, {})),
            "new_avg_score":  _site_avg_score(data),
        }
        merged_results[site] = data

    # Rebuild map data with updated scores
    from map_data import build_map_data_from_msl
    merged_msl = baseline.get("msl_sites", [])
    merged_map  = _rebuild_map(baseline.get("map_data"), merged_results)

    return merged_results, merged_msl, merged_map


def get_baseline_files(run_id):
    """
    Return (foreseer_bytes, dict_bytes, dict_filename) stored in a full run.
    Returns (None, None, None) if not found or not a full run.
    """
    run = load_run(run_id)
    if not run:
        return None, None, None
    fb  = _unb64(run.get("foreseer_b64"))
    db  = _unb64(run.get("dict_b64"))
    dfn = run.get("dict_filename", "dictionary.csv")
    return fb, db, dfn


# ── Load / list / delete ──────────────────────────────────────────────────

def list_runs():
    _ensure()
    runs = []
    for fname in os.listdir(RUNS_DIR):
        if not fname.endswith(".json.gz"):
            continue
        try:
            with gzip.open(os.path.join(RUNS_DIR, fname), "rt", encoding="utf-8") as f:
                d = json.load(f)
            runs.append({
                "id":            d["id"],
                "name":          d["name"],
                "run_type":      d.get("run_type", "full"),
                "parent_run_id": d.get("parent_run_id"),
                "created_at":    d["created_at"],
                "sites_count":   d["sites_count"],
                "avg_score":     d["avg_score"],
                "changed_sites": d.get("changed_sites", []),
            })
        except Exception as e:
            print(f"Could not read {fname}: {e}")
    return sorted(runs, key=lambda r: r["created_at"], reverse=True)


def load_run(run_id):
    _ensure()
    for fname in os.listdir(RUNS_DIR):
        if fname.startswith(run_id) and fname.endswith(".json.gz"):
            with gzip.open(os.path.join(RUNS_DIR, fname), "rt", encoding="utf-8") as f:
                return json.load(f)
    return None


def load_latest_run():
    runs = list_runs()
    return load_run(runs[0]["id"]) if runs else None


def delete_run(run_id):
    for fname in os.listdir(RUNS_DIR):
        if fname.startswith(run_id) and fname.endswith(".json.gz"):
            os.remove(os.path.join(RUNS_DIR, fname))
            return True
    return False


# ── Helpers ───────────────────────────────────────────────────────────────

def _b64(data):
    import base64
    return base64.b64encode(data).decode() if data else None


def _unb64(s):
    import base64
    return base64.b64decode(s) if s else None


def _site_avg_score(site_data):
    rows = [r for r in site_data.get("reconciliation", [])
            if r.get("device_type") != "TOTAL_ASSETS_ALL_TYPES"
            and r.get("match_score") is not None
            and ((r.get("foreseer_count") or 0) > 0 or (r.get("linx_count") or 0) > 0)]
    scores = [float(r["match_score"]) for r in rows]
    return round(sum(scores) / len(scores), 1) if scores else None


def _rebuild_map(existing_map, results):
    """Update site avg scores in existing map data."""
    if not existing_map:
        return existing_map
    from utils_map import score_sites
    return score_sites(existing_map, results)
