"""
Builds GeoJSON for the map tab:
 - Region convex hull polygons from MSL lat/lon grouped by region
 - Site markers with lat/lon, region, avg score placeholder
"""
import openpyxl
import io
from collections import defaultdict


def build_map_data(foreseer_bytes, results=None):
    """
    Returns dict with:
      regions: GeoJSON FeatureCollection of convex hull polygons per region
      sites:   list of site dicts with lat, lon, region, site_dns, avg_score
    """
    wb = openpyxl.load_workbook(
        io.BytesIO(foreseer_bytes), read_only=True, data_only=True, keep_vba=False
    )
    ws = wb["MSL"]

    region_points  = defaultdict(list)  # region -> [(lat, lon, dns)]
    division_points = defaultdict(list)
    site_list = []

    for row in ws.iter_rows(min_row=2, max_row=5000, values_only=True):
        region   = str(row[2] or "").strip()
        division = str(row[1] or "").strip()
        lat_raw  = row[41]
        lon_raw  = row[40]
        full_dns = str(row[18] or "").strip()
        site_name = str(row[5] or "").strip()

        if not region or not lat_raw or not lon_raw:
            continue
        if region in ("DELETE", "IT", "Test Region", "LABS"):
            continue

        try:
            lat = float(lat_raw)
            lon = float(lon_raw)
        except (TypeError, ValueError):
            continue

        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue

        # Derive short dns
        parts = full_dns.split(".")
        short_dns = ".".join(parts[:2]).lower() if len(parts) >= 2 else full_dns.lower()

        region_points[region].append((lat, lon))
        division_points[division].append((lat, lon))

        # Get avg score from results if available
        avg_score = None
        has_foreseer = None
        if results and short_dns in results:
            site_data = results[short_dns]
            recon = site_data.get("reconciliation", [])
            active = [r for r in recon
                      if r.get("device_type") != "TOTAL_ASSETS_ALL_TYPES"
                      and (r.get("foreseer_count", 0) or 0) > 0]
            if active:
                scores = [float(r["match_score"]) for r in active if r.get("match_score") is not None]
                avg_score = round(sum(scores) / len(scores)) if scores else None
                has_foreseer = True
            else:
                has_foreseer = False

        site_list.append({
            "site":       site_name,
            "short_dns":  short_dns,
            "lat":        lat,
            "lon":        lon,
            "region":     region,
            "division":   division,
            "avg_score":  avg_score,
            "has_foreseer": has_foreseer,
        })

    wb.close()

    # Deduplicate sites (MSL has some duplicates)
    seen = set()
    deduped_sites = []
    for s in site_list:
        key = (s["short_dns"], s["region"])
        if key not in seen:
            seen.add(key)
            deduped_sites.append(s)

    region_hulls   = _build_hulls(region_points)
    division_hulls = _build_hulls(division_points)

    return {
        "regions":   region_hulls,
        "divisions": division_hulls,
        "sites":     deduped_sites,
    }


def _build_hulls(points_by_group):
    """Compute convex hull per group, return GeoJSON FeatureCollection."""
    try:
        from scipy.spatial import ConvexHull
        import numpy as np
        has_scipy = True
    except ImportError:
        has_scipy = False

    features = []
    for group_name, pts in points_by_group.items():
        if group_name in ("DELETE", "IT", "Test Region", "LABS"):
            continue
        if len(pts) < 3:
            # Not enough points for a hull — add single point or skip
            continue

        if has_scipy:
            try:
                arr = np.array(pts)
                hull = ConvexHull(arr)
                # Hull vertices in order, close the polygon
                hull_pts = arr[hull.vertices].tolist()
                hull_pts.append(hull_pts[0])  # close ring
                # GeoJSON uses [lon, lat]
                coords = [[p[1], p[0]] for p in hull_pts]
            except Exception:
                coords = _simple_bbox(pts)
        else:
            coords = _simple_bbox(pts)

        features.append({
            "type": "Feature",
            "properties": {"name": group_name, "count": len(pts)},
            "geometry": {
                "type": "Polygon",
                "coordinates": [coords],
            },
        })

    return {"type": "FeatureCollection", "features": features}


def _simple_bbox(pts):
    """Fallback: bounding box polygon when scipy unavailable."""
    lats = [p[0] for p in pts]
    lons = [p[1] for p in pts]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    return [
        [min_lon, min_lat], [max_lon, min_lat],
        [max_lon, max_lat], [min_lon, max_lat],
        [min_lon, min_lat],
    ]
