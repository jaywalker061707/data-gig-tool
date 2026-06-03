"""
Excel export — generates a multi-tab workbook from reconciliation results.
Tabs: Batch Summary + one tab per site + All Detail
"""
import io
import openpyxl
from openpyxl.styles import (PatternFill, Font, Alignment, Border, Side,
                              GradientFill)
from openpyxl.utils import get_column_letter

# ── Colors ──────────────────────────────────────────────────────────────────
COMCAST_BLUE  = "0061A0"
WHITE         = "FFFFFF"
GRAY_HEADER   = "F1F5F9"
GRAY_BORDER   = "CBD5E1"

FILL_MATCH    = PatternFill("solid", fgColor="DCFCE7")
FILL_FORESEER = PatternFill("solid", fgColor="FEF9C3")
FILL_LINX     = PatternFill("solid", fgColor="FCE7F3")
FILL_MISMATCH = PatternFill("solid", fgColor="FFEDD5")
FILL_NONE     = PatternFill("solid", fgColor="F8FAFC")
FILL_TOTAL    = PatternFill("solid", fgColor="E2E8F0")
FILL_HEADER   = PatternFill("solid", fgColor=COMCAST_BLUE)

STATUS_FILL = {
    "Match":                                FILL_MATCH,
    "Mismatch / Needs review":              FILL_MISMATCH,
    "Present in Foreseer, Missing in LinX": FILL_FORESEER,
    "Present in LinX, Missing in Foreseer": FILL_LINX,
    "No records in either system":          FILL_NONE,
}

thin = Side(style="thin", color=GRAY_BORDER)
BORDER = Border(left=thin, right=thin, top=thin, bottom=thin)


def _hdr_font(bold=True, color=WHITE):
    return Font(bold=bold, color=color, name="Segoe UI", size=10)

def _cell_font(bold=False, color="0F172A"):
    return Font(bold=bold, color=color, name="Segoe UI", size=9)

def _apply_header(ws, headers, row=1):
    for col, text in enumerate(headers, 1):
        c = ws.cell(row=row, column=col, value=text)
        c.fill   = FILL_HEADER
        c.font   = _hdr_font()
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = BORDER

def _write_row(ws, row_num, values, fill=None, bold=False):
    for col, val in enumerate(values, 1):
        c = ws.cell(row=row_num, column=col, value=val)
        c.font   = _cell_font(bold=bold)
        c.border = BORDER
        c.alignment = Alignment(vertical="top", wrap_text=False)
        if fill:
            c.fill = fill

def _autofit(ws, max_width=60):
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            try:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
            except:
                pass
        ws.column_dimensions[col_letter].width = min(max(max_len + 2, 10), max_width)

def _freeze(ws, cell="B2"):
    ws.freeze_panes = cell


# ── Site detail tab ──────────────────────────────────────────────────────────

DETAIL_HEADERS = [
    "Device Type", "Foreseer Count", "LinX Count", "Count Diff", "Pct Diff %",
    "Match Status", "Score",
    "LinX Missing Serials", "LinX Missing IPs", "Foreseer Missing IPs",
    "IP Mismatch Flag",
    "Notes",
    "Foreseer Asset IPs", "LinX Asset IPs",
    "LinX Assets Missing Serial", "LinX Assets Missing IP",
    "Foreseer IPs Not in LinX", "LinX IPs Not in Foreseer",
]

def _write_site_tab(wb, site_dns, site_data):
    # Sanitize sheet name (Excel max 31 chars, no special chars)
    sheet_name = site_dns[:31].replace("/","_").replace("\\","_").replace("?","_").replace("*","_").replace("[","(").replace("]",")")
    ws = wb.create_sheet(title=sheet_name)

    # Title row
    ws.merge_cells(f"A1:{get_column_letter(len(DETAIL_HEADERS))}1")
    title_cell = ws["A1"]
    title_cell.value = f"GIG Reconciliation — {site_dns}"
    title_cell.font  = Font(bold=True, color=WHITE, size=12, name="Segoe UI")
    title_cell.fill  = FILL_HEADER
    title_cell.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 22

    # Sanity block
    sanity = site_data.get("sanity", {})
    ws["A2"] = f"Foreseer rows: {sanity.get('foreseer_raw_rows','?')}  |  LinX rows: {sanity.get('linx_raw_rows','?')}  |  After project filter: {sanity.get('linx_after_project_filter','?')}  |  Dict entries: {sanity.get('dict_entries','?')}"
    ws["A2"].font = Font(italic=True, size=9, color="64748B", name="Segoe UI")
    ws.row_dimensions[2].height = 14

    _apply_header(ws, DETAIL_HEADERS, row=3)
    ws.row_dimensions[3].height = 30

    recon = site_data.get("reconciliation", [])
    data_rows = [r for r in recon if r.get("device_type") != "TOTAL_ASSETS_ALL_TYPES"]
    total_row  = next((r for r in recon if r.get("device_type") == "TOTAL_ASSETS_ALL_TYPES"), None)

    # Sort: largest abs diff first, then alpha
    data_rows.sort(key=lambda r: (-abs(int(r.get("count_difference") or 0)), str(r.get("device_type",""))))

    excel_row = 4
    for r in data_rows:
        status = r.get("match_status", "")
        fill   = STATUS_FILL.get(status, FILL_NONE)
        f_count = r.get("foreseer_count", 0)
        l_count = r.get("linx_count", 0)
        if (f_count or 0) == 0 and (l_count or 0) == 0:
            fill = FILL_NONE

        vals = [
            r.get("device_type"),
            _int(r.get("foreseer_count")),
            _int(r.get("linx_count")),
            _int(r.get("count_difference")),
            _float(r.get("pct_difference")),
            status,
            _int(r.get("match_score")),
            _int(r.get("linx_missing_serial_count")),
            _int(r.get("linx_missing_ip_count")),
            _int(r.get("foreseer_missing_ip_count")),
            _int(r.get("ip_mismatch_flag")),
            r.get("notes") or "",
            r.get("foreseer_asset_ip_addresses") or "",
            r.get("linx_asset_ip_addresses") or "",
            r.get("linx_assets_missing_serial") or "",
            r.get("linx_assets_missing_ip") or "",
            r.get("foreseer_ips_not_in_linx") or "",
            r.get("linx_ips_not_in_foreseer") or "",
        ]
        _write_row(ws, excel_row, vals, fill=fill)
        excel_row += 1

    # Total row
    if total_row:
        vals = [
            "TOTAL",
            _int(total_row.get("foreseer_count")),
            _int(total_row.get("linx_count")),
            _int(total_row.get("count_difference")),
            _float(total_row.get("pct_difference")),
            "", "",
            _int(total_row.get("linx_missing_serial_count")),
            _int(total_row.get("linx_missing_ip_count")),
            _int(total_row.get("foreseer_missing_ip_count")),
            "", "", "", "", "", "", "", "",
        ]
        _write_row(ws, excel_row, vals, fill=FILL_TOTAL, bold=True)

    # Column widths (manual for key cols)
    ws.column_dimensions["A"].width = 42
    ws.column_dimensions["F"].width = 34
    ws.column_dimensions["L"].width = 55
    ws.column_dimensions["M"].width = 70
    ws.column_dimensions["N"].width = 70
    for col in ["B","C","D","E","G","H","I","J","K"]:
        ws.column_dimensions[col].width = 14

    _freeze(ws, "B4")
    ws.auto_filter.ref = f"A3:{get_column_letter(len(DETAIL_HEADERS))}{excel_row}"
    return ws


# ── Batch Summary tab ────────────────────────────────────────────────────────

BATCH_HEADERS = ["Site", "Foreseer Devices", "LinX Assets", "Active Types",
                 "Matched", "Needs Review", "Foreseer Only", "LinX Only", "Avg Score"]

def _write_batch_tab(wb, results):
    ws = wb.active
    ws.title = "Batch Summary"

    ws.merge_cells(f"A1:{get_column_letter(len(BATCH_HEADERS))}1")
    c = ws["A1"]
    c.value = "GIG Data Integrity — Batch Summary"
    c.font  = Font(bold=True, color=WHITE, size=13, name="Segoe UI")
    c.fill  = FILL_HEADER
    c.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 26

    _apply_header(ws, BATCH_HEADERS, row=2)
    ws.row_dimensions[2].height = 22

    summaries = []
    for site_dns, site_data in results.items():
        recon  = site_data.get("reconciliation", [])
        active = [r for r in recon if r.get("device_type") != "TOTAL_ASSETS_ALL_TYPES"
                  and ((r.get("foreseer_count") or 0) > 0 or (r.get("linx_count") or 0) > 0)]
        total  = next((r for r in recon if r.get("device_type") == "TOTAL_ASSETS_ALL_TYPES"), {})
        scores = [int(r["match_score"]) for r in active if r.get("match_score") is not None]
        avg_score = round(sum(scores)/len(scores)) if scores else None

        summaries.append({
            "site": site_dns,
            "foreseer": _int(total.get("foreseer_count")),
            "linx":     _int(total.get("linx_count")),
            "active":   len(active),
            "matched":  sum(1 for r in active if r.get("match_status") == "Match"),
            "review":   sum(1 for r in active if r.get("match_status") == "Mismatch / Needs review"),
            "f_only":   sum(1 for r in active if r.get("match_status") == "Present in Foreseer, Missing in LinX"),
            "l_only":   sum(1 for r in active if r.get("match_status") == "Present in LinX, Missing in Foreseer"),
            "score":    avg_score,
        })

    for i, s in enumerate(summaries, 3):
        score = s["score"]
        score_fill = _score_fill(score)
        vals = [s["site"], s["foreseer"], s["linx"], s["active"],
                s["matched"], s["review"], s["f_only"], s["l_only"], score]
        for col, val in enumerate(vals, 1):
            c = ws.cell(row=i, column=col, value=val)
            c.font   = _cell_font(bold=(col==1))
            c.border = BORDER
            c.alignment = Alignment(vertical="center")
            if col == 9 and score is not None:
                c.fill = score_fill

    ws.column_dimensions["A"].width = 28
    for col in ["B","C","D","E","F","G","H","I"]:
        ws.column_dimensions[col].width = 16

    _freeze(ws, "B3")
    ws.auto_filter.ref = f"A2:{get_column_letter(len(BATCH_HEADERS))}{len(summaries)+2}"


# ── Main export function ─────────────────────────────────────────────────────

PAIR_HEADERS = [
    "Device Type", "Match Method",
    "Foreseer Device", "Foreseer IP", "Foreseer Serial",
    "LinX Asset ID", "LinX Asset Name", "LinX IP", "LinX Serial",
]

PAIR_METHOD_FILL = {
    "IP Match":      PatternFill("solid", fgColor="DCFCE7"),
    "Serial Match":  PatternFill("solid", fgColor="D1FAE5"),
    "Foreseer Only": PatternFill("solid", fgColor="FEF9C3"),
    "LinX Only":     PatternFill("solid", fgColor="FCE7F3"),
}

def _write_pairs_tab(wb, site_dns, pairs):
    sheet_name = (site_dns[:25] + " Pairs")[:31]
    ws = wb.create_sheet(title=sheet_name)

    ws.merge_cells(f"A1:{get_column_letter(len(PAIR_HEADERS))}1")
    c = ws["A1"]
    c.value = f"Asset-Level Matching — {site_dns}"
    c.font  = Font(bold=True, color=WHITE, size=12, name="Segoe UI")
    c.fill  = FILL_HEADER
    c.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 22

    # Legend
    ws["A2"] = "Green = IP Match  |  Teal = Serial Match  |  Yellow = Foreseer Only (no LinX match)  |  Pink = LinX Only (no Foreseer match)"
    ws["A2"].font = Font(italic=True, size=9, color="64748B", name="Segoe UI")

    _apply_header(ws, PAIR_HEADERS, row=3)
    ws.row_dimensions[3].height = 22

    # Sort: matched first, then unmatched
    method_order = {"IP Match": 0, "Serial Match": 1, "Foreseer Only": 2, "LinX Only": 3}
    sorted_pairs = sorted(pairs, key=lambda p: (
        p.get("device_type", ""),
        method_order.get(p.get("match_method", ""), 9),
        p.get("foreseer_device") or "",
        p.get("linx_asset_id") or "",
    ))

    excel_row = 4
    for p in sorted_pairs:
        method = p.get("match_method", "")
        fill   = PAIR_METHOD_FILL.get(method, PatternFill())
        vals = [
            p.get("device_type"),
            method,
            p.get("foreseer_device") or "",
            p.get("foreseer_ip")     or "",
            p.get("foreseer_serial") or "",
            p.get("linx_asset_id")   or "",
            p.get("linx_asset_name") or "",
            p.get("linx_ip")         or "",
            p.get("linx_serial")     or "",
        ]
        _write_row(ws, excel_row, vals, fill=fill)
        excel_row += 1

    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 32
    ws.column_dimensions["D"].width = 16
    ws.column_dimensions["E"].width = 22
    ws.column_dimensions["F"].width = 28
    ws.column_dimensions["G"].width = 28
    ws.column_dimensions["H"].width = 16
    ws.column_dimensions["I"].width = 22

    _freeze(ws, "B4")
    ws.auto_filter.ref = f"A3:{get_column_letter(len(PAIR_HEADERS))}{excel_row - 1}"

    # Summary counts at bottom
    from collections import Counter
    counts = Counter(p.get("match_method") for p in pairs)
    ws.cell(row=excel_row + 1, column=1, value="Summary:").font = Font(bold=True, name="Segoe UI", size=9)
    for i, (method, count) in enumerate(sorted(counts.items(), key=lambda x: method_order.get(x[0], 9))):
        ws.cell(row=excel_row + 1, column=2 + i, value=f"{method}: {count}").font = Font(name="Segoe UI", size=9)


def build_excel(results):
    wb = openpyxl.Workbook()
    _write_batch_tab(wb, results)

    for site_dns, site_data in results.items():
        _write_site_tab(wb, site_dns, site_data)
        pairs = site_data.get("asset_pairs", [])
        if pairs:
            _write_pairs_tab(wb, site_dns, pairs)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _int(v):
    if v is None: return None
    try: return int(v)
    except: return v

def _float(v):
    if v is None: return None
    try: return round(float(v), 1)
    except: return v

def _score_fill(score):
    if score is None: return PatternFill()
    if score >= 90: return PatternFill("solid", fgColor="DCFCE7")
    if score >= 75: return PatternFill("solid", fgColor="D1FAE5")
    if score >= 50: return PatternFill("solid", fgColor="FEF9C3")
    if score >= 25: return PatternFill("solid", fgColor="FFEDD5")
    return PatternFill("solid", fgColor="FEE2E2")
