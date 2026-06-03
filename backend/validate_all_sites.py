import sys, zipfile, xml.etree.ElementTree as ET, os
sys.stdout.reconfigure(encoding='utf-8')
from lambda_function import run_reconciliation, load_msl

DATA = r"C:\Users\Jaywa\Desktop\Data Gig Files"

with open(os.path.join(DATA, "foreseer updated.xlsm"), "rb") as f: fb = f.read()
with open(os.path.join(DATA, "AssetTypeDictionary_202605191411 (1).csv"), "rb") as f: db = f.read()
msl = load_msl(fb)

ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
with zipfile.ZipFile(os.path.join(DATA, "batch_reconciliation_20260601_Jay.xlsx")) as z:
    shared = ["".join(t.text or "" for t in si.findall(".//x:t", ns))
              for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("x:si", ns)]
    def rs(n):
        rows = []
        for row in ET.fromstring(z.read(f"xl/worksheets/sheet{n}.xml")).findall(".//x:row", ns):
            vals = []
            for c in row.findall("x:c", ns):
                t, v = c.get("t"), c.find("x:v", ns)
                if v is None: vals.append(None)
                elif t == "s": vals.append(shared[int(v.text)])
                else:
                    try: vals.append(float(v.text))
                    except: vals.append(v.text)
            rows.append(vals)
        return {r[0]: r for r in rows[1:] if r[0] and r[0] != "TOTAL_ASSETS_ALL_TYPES"}
    drew = {
        "venice.fl":    rs(2),
        "verobeach.fl": rs(3),
        "wakulla.fl":   rs(4),
        "westboca.fl":  rs(5),
    }

sites = {
    "venice.fl":    "venice.fl.xlsx",
    "verobeach.fl": "verobeach.fl.xlsx",
    "wakulla.fl":   "wakulla.fl.xlsx",
    "westboca.fl":  "westboca.fl.xlsx",
}

total_diffs = 0
for site, fname in sites.items():
    with open(os.path.join(DATA, fname), "rb") as f: lb = f.read()
    res = run_reconciliation(fb, [lb], db, msl)
    our = {r["device_type"]: r for r in res.get(site, {}).get("reconciliation", [])
           if r["device_type"] != "TOTAL_ASSETS_ALL_TYPES"}
    dr = drew[site]
    all_t = sorted(set(list(our.keys()) + list(dr.keys())))
    site_diffs = 0
    for dt in all_t:
        o = our.get(dt)
        d = dr.get(dt)
        of = int(o["foreseer_count"]) if o else 0
        ol = int(o["linx_count"]) if o else 0
        df = int(d[1] or 0) if d else 0
        dl = int(d[2] or 0) if d else 0
        if of == 0 and ol == 0 and df == 0 and dl == 0:
            continue
        if of != df or ol != dl:
            site_diffs += 1
            total_diffs += 1
            print(f"{site:<14} {dt[:40]:<40} OurF={of:>3} DrwF={df:>3} OurL={ol:>3} DrwL={dl:>3}")
    if site_diffs == 0:
        tot = next((r for r in res.get(site, {}).get("reconciliation", [])
                    if r["device_type"] == "TOTAL_ASSETS_ALL_TYPES"), {})
        print(f"{site}: PERFECT MATCH  (F={tot.get('foreseer_count',0)} L={tot.get('linx_count',0)})")

print(f"\nTotal diffs: {total_diffs}")
