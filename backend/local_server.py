"""
GIG Data Integrity Tool — Backend Server
"""
import sys, os, traceback, io, uuid, threading
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from lambda_function import run_reconciliation, run_site_detail, load_msl
from export import build_excel
from map_data import build_map_data
from runs_store import (save_run, list_runs, load_run, load_latest_run,
                        delete_run, apply_delta, get_baseline_files)

app  = Flask(__name__)
CORS(app)

# In-memory job store: job_id -> {"state": "queued|processing|complete|error", ...}
_jobs = {}
_jobs_lock = threading.Lock()

def _set_job(job_id, state, extra=None):
    with _jobs_lock:
        _jobs[job_id] = {"state": state, **(extra or {})}

def _get_job_state(job_id):
    with _jobs_lock:
        return _jobs.get(job_id)

# Serve React build in production
FRONTEND_BUILD = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.exists(FRONTEND_BUILD):
    from flask import send_from_directory
    @app.route("/gig-integrity-tool/", defaults={"path": ""})
    @app.route("/gig-integrity-tool/<path:path>")
    def serve_frontend(path):
        full = os.path.join(FRONTEND_BUILD, path)
        if path and os.path.exists(full):
            return send_from_directory(FRONTEND_BUILD, path)
        return send_from_directory(FRONTEND_BUILD, "index.html")


# ── Runs ──────────────────────────────────────────────────────────────────

@app.route("/api/runs", methods=["GET"])
def handle_list_runs():
    return jsonify(list_runs())


@app.route("/api/runs/latest", methods=["GET"])
def handle_latest_run():
    run = load_latest_run()
    if not run:
        return jsonify({"error": "No saved runs"}), 404
    # Don't send stored file bytes to frontend
    run.pop("foreseer_b64", None)
    run.pop("dict_b64", None)
    return jsonify(run)


@app.route("/api/runs/<run_id>", methods=["GET"])
def handle_load_run(run_id):
    run = load_run(run_id)
    if not run:
        return jsonify({"error": f"Run {run_id} not found"}), 404
    run.pop("foreseer_b64", None)
    run.pop("dict_b64", None)
    return jsonify(run)


@app.route("/api/runs/<run_id>", methods=["DELETE"])
def handle_delete_run(run_id):
    return jsonify({"deleted": delete_run(run_id)})


# ── Job status polling ────────────────────────────────────────────────────

@app.route("/api/jobs/<job_id>", methods=["GET"])
def handle_job_status(job_id):
    job = _get_job_state(job_id)
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


# ── Full reconciliation run (async) ──────────────────────────────────────

@app.route("/api/run", methods=["POST"])
def handle_run():
    try:
        ff = request.files.get("foreseer")
        lf = request.files.getlist("linx")
        df = request.files.get("dict")

        if not ff or not ff.filename: return jsonify({"error": "Foreseer file required"}), 400
        if not lf or not any(f.filename for f in lf): return jsonify({"error": "LinX file(s) required"}), 400
        if not df or not df.filename: return jsonify({"error": "Dictionary file required"}), 400

        fb       = ff.read()
        lb       = [f.read() for f in lf if f.filename]
        db       = df.read()
        dict_fn  = df.filename
        run_name = request.form.get("run_name", "").strip() or _default_name(lb)
        job_id   = str(uuid.uuid4())

        _set_job(job_id, "queued", {"run_name": run_name})

        def _process():
            try:
                _set_job(job_id, "processing", {"message": "Running reconciliation...", "run_name": run_name})
                print(f"Full run: '{run_name}' (job {job_id})")
                msl_sites = load_msl(fb)
                results   = run_reconciliation(fb, lb, db, msl_sites, dict_fn)
                map_data  = build_map_data(fb, results)
                run_id    = save_run(
                    name=run_name, results=results, msl_sites=msl_sites, map_data=map_data,
                    run_type="full", foreseer_bytes=fb, dict_bytes=db, dict_filename=dict_fn,
                )
                _set_job(job_id, "complete", {
                    "run_id": run_id, "run_name": run_name,
                    "results": results, "msl_sites": msl_sites, "map_data": map_data,
                })
                print(f"Full run complete: '{run_name}' (job {job_id})")
            except Exception:
                err = traceback.format_exc()
                print(err)
                _set_job(job_id, "error", {"message": err})

        threading.Thread(target=_process, daemon=True).start()
        return jsonify({"job_id": job_id, "run_name": run_name,
                        "message": "Processing started. Poll /api/jobs/{job_id} for status."}), 202


# ── Delta run — upload 1-N site LinX files, merge into baseline ───────────

@app.route("/api/run-delta", methods=["POST"])
def handle_run_delta():
    try:
        baseline_id = request.form.get("baseline_run_id", "")
        if not baseline_id:
            return jsonify({"error": "baseline_run_id required"}), 400

        lf = request.files.getlist("linx")
        if not lf or not any(f.filename for f in lf):
            return jsonify({"error": "At least one LinX file required"}), 400

        run_name = request.form.get("run_name", "").strip()
        lb       = [f.read() for f in lf if f.filename]
        job_id   = str(uuid.uuid4())

        _set_job(job_id, "queued", {"run_name": run_name or "Delta Update"})

        def _process():
            try:
                _set_job(job_id, "processing", {"message": "Loading baseline...", "run_name": run_name})
                fb, db, dict_fn = get_baseline_files(baseline_id)
                if not fb or not db:
                    _set_job(job_id, "error", {"message": "Baseline run does not have stored Foreseer/Dictionary files. Please run a full reconciliation first."})
                    return

                msl_sites_full = load_msl(fb)
                _set_job(job_id, "processing", {"message": "Running delta reconciliation..."})
                new_results   = run_reconciliation(fb, lb, db, msl_sites_full, dict_fn)
                changed_sites = list(new_results.keys())

                rn = run_name or f"Delta — {', '.join(changed_sites[:3])}{'...' if len(changed_sites) > 3 else ''}"

                merged_results, merged_msl, merged_map = apply_delta(
                    baseline_id, new_results, msl_sites_full, None, rn, changed_sites
                )
                run_id = save_run(
                    name=rn, results=merged_results, msl_sites=merged_msl, map_data=merged_map,
                    run_type="delta", parent_run_id=baseline_id, changed_sites=changed_sites,
                )
                print(f"Delta run saved: {run_id} — {len(changed_sites)} site(s)")
                _set_job(job_id, "complete", {
                    "run_id": run_id, "run_name": rn, "changed_sites": changed_sites,
                    "results": merged_results, "msl_sites": merged_msl, "map_data": merged_map,
                })
            except Exception:
                err = traceback.format_exc()
                print(err)
                _set_job(job_id, "error", {"message": err})

        threading.Thread(target=_process, daemon=True).start()
        return jsonify({"job_id": job_id, "message": "Delta processing started."}), 202
    except Exception as e:
        print(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


# ── Site detail (on-demand) ────────────────────────────────────────────────

@app.route("/api/site-detail", methods=["POST"])
def handle_site_detail():
    try:
        baseline_id = request.form.get("baseline_run_id", "")
        site_dns    = request.form.get("site_dns", "")
        if not site_dns:
            return jsonify({"error": "site_dns required"}), 400

        # Try to get files from uploaded or from baseline
        ff = request.files.get("foreseer")
        lf = request.files.getlist("linx")
        df = request.files.get("dict")

        if ff and ff.filename and lf and df:
            fb = ff.read(); lb = [f.read() for f in lf if f.filename]; db = df.read(); dict_fn = df.filename
        elif baseline_id:
            fb, db, dict_fn = get_baseline_files(baseline_id)
            # Need LinX for this specific site from the baseline stored linx
            # For now use the most recent run's linx bytes
            if not fb:
                return jsonify({"error": "No Foreseer/Dict in baseline. Please upload files."}), 400
            lb = lf  # empty — site-detail query uses alarmGroupName filter so full foreseer is fine
        else:
            return jsonify({"error": "Either upload files or provide baseline_run_id"}), 400

        detail = run_site_detail(fb, lb if lb else [b""], db, site_dns, dict_fn)
        return jsonify(detail)
    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


# ── Export ────────────────────────────────────────────────────────────────

@app.route("/api/export", methods=["POST"])
def handle_export():
    try:
        results = request.get_json().get("results", {})
        buf = io.BytesIO(build_excel(results))
        return send_file(buf,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True, download_name="GIG_Reconciliation_Results.xlsx")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── AI Chat ───────────────────────────────────────────────────────────────

@app.route("/api/chat", methods=["POST"])
def handle_chat():
    try:
        body    = request.get_json()
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return jsonify({"reply": "AI chat requires ANTHROPIC_API_KEY environment variable."})
        import anthropic
        resp = anthropic.Anthropic(api_key=api_key).messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=512,
            system=f"You are a data analyst for Comcast GIG Data Integrity. Be concise.\n\nContext:\n{body.get('context','')}",
            messages=[{"role": "user", "content": body.get("message", "")}],
        )
        return jsonify({"reply": resp.content[0].text})
    except Exception as e:
        return jsonify({"reply": f"Error: {e}"}), 500


def _default_name(linx_list):
    from datetime import datetime
    d = datetime.now()
    n = len(linx_list)
    return f"{d.strftime('%b %d %Y')} — {n} LinX file{'s' if n != 1 else ''}"


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"GIG backend -> http://localhost:{port}")
    runs = list_runs()
    if runs:
        print(f"{len(runs)} saved run(s):")
        for r in runs[:3]:
            print(f"  [{r['run_type']}] {r['name']} | {r['created_at'][:10]} | {r['sites_count']} sites | score {r['avg_score']}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
