"""Utility to update map site scores after a delta run."""

def score_sites(map_data, results):
    """Update avg_score on each site in map_data based on current results."""
    if not map_data or not map_data.get("sites"):
        return map_data

    score_map = {}
    for site_dns, site_data in results.items():
        rows = [r for r in site_data.get("reconciliation", [])
                if r.get("device_type") != "TOTAL_ASSETS_ALL_TYPES"
                and r.get("match_score") is not None
                and ((r.get("foreseer_count") or 0) > 0 or (r.get("linx_count") or 0) > 0)]
        scores = [float(r["match_score"]) for r in rows]
        score_map[site_dns] = round(sum(scores) / len(scores), 1) if scores else None

    updated_sites = []
    for site in map_data["sites"]:
        s = dict(site)
        dns = s.get("short_dns", "")
        if dns in score_map:
            s["avg_score"] = score_map[dns]
        updated_sites.append(s)

    return {**map_data, "sites": updated_sites}
