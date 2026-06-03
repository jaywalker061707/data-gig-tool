"""
Local validation test — compares our SQL output against Drew's known-good output.
Usage: python test_local.py
"""
import json, sys, os, zipfile, xml.etree.ElementTree as ET
sys.path.insert(0, os.path.dirname(__file__))
from lambda_function import run_reconciliation, load_msl

DATA_DIR = r"C:\Users\Jaywa\Desktop\Data Gig Files"

foreseer_path = os.path.join(DATA_DIR, "foreseer updated.xlsm")
linx_path     = os.path.join(DATA_DIR, "venice.fl.xlsx")
dict_path     = os.path.join(DATA_DIR, "AssetTypeDictionary_202605191411 (1).csv")
drew_path     = os.path.join(DATA_DIR, "batch_reconciliation_20260601_Jay.xlsx")

with open(foreseer_path, "rb") as f: foreseer_bytes = f.read()
with open(linx_path, "rb") as f:     linx_bytes = f.read()
with open(dict_path, "rb") as f:     dict_bytes = f.read()

msl_sites = load_msl(foreseer_bytes)
print(f"Running reconciliation for venice.fl...")
results = run_reconciliation(foreseer_bytes, [linx_bytes], dict_bytes, msl_sites)

our_rows = {}
for site, data in results.items():
    if "error" in data:
        print(f"ERROR: {data['error']}")
        sys.exit(1)
    print(f"Sanity: {data['sanity']}")
    for row in data["reconciliation"]:
        if row["device_type"] != "TOTAL_ASSETS_ALL_TYPES":
            our_rows[row["device_type"]] = row

# Load Drew's venice.fl output
def load_drew(path):
    with zipfile.ZipFile(path) as z:
        ss_xml = z.read('xl/sharedStrings.xml')
        ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        ss_root = ET.fromstring(ss_xml)
        shared = [''.join(t.text or '' for t in si.findall('.//x:t', ns))
                  for si in ss_root.findall('x:si', ns)]
        sh = z.read('xl/worksheets/sheet2.xml')  # venice.fl is sheet2
        root = ET.fromstring(sh)
        rows = []
        for row in root.findall('.//x:row', ns):
            vals = []
            for cell in row.findall('x:c', ns):
                t, v_el = cell.get('t'), cell.find('x:v', ns)
                if v_el is None: vals.append(None)
                elif t == 's': vals.append(shared[int(v_el.text)])
                else:
                    try: vals.append(float(v_el.text))
                    except: vals.append(v_el.text)
            rows.append(vals)
    headers = rows[0]
    return {r[0]: dict(zip(headers, r)) for r in rows[1:] if r[0]}

drew_rows = load_drew(drew_path)

# Compare active rows only
print(f"\n{'Device Type':<48} {'Ours F':>6} {'Drew F':>6} {'Ours L':>6} {'Drew L':>6} {'Match':>6}")
print("-" * 90)

all_types = sorted(set(list(our_rows.keys()) + list(drew_rows.keys())))
mismatches = 0
for dt in all_types:
    ours = our_rows.get(dt)
    drew = drew_rows.get(dt)
    if ours is None and drew is None: continue
    of = int(ours["foreseer_count"]) if ours else 0
    ol = int(ours["linx_count"]) if ours else 0
    df = int(drew["foreseer_count"]) if drew else 0
    dl = int(drew["linx_count"]) if drew else 0
    if of == 0 and ol == 0 and df == 0 and dl == 0: continue
    match = "OK" if of == df and ol == dl else "DIFF"
    if match != "✓": mismatches += 1
    print(f"{dt[:47]:<48} {of:>6} {df:>6} {ol:>6} {dl:>6} {match:>6}")

print(f"\nMismatches: {mismatches} / {len(all_types)} device types")
