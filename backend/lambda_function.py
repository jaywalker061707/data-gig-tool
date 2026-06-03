import json
import os
import io
import duckdb
import openpyxl
import csv
import boto3
import pandas as pd

s3 = boto3.client("s3")
BUCKET = os.environ.get("S3_BUCKET", "gig-data-integrity-tool")


# ---------------------------------------------------------------------------
# File loaders — return list of dicts (one per row)
# ---------------------------------------------------------------------------

def load_excel_sheet(file_bytes, sheet_name=None):
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True, keep_vba=False)
    ws = wb[sheet_name] if sheet_name else wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return []
    headers = [str(h).strip() if h is not None else f"col_{i}" for i, h in enumerate(rows[0])]
    result = []
    for row in rows[1:]:
        if all(v is None for v in row):
            continue
        result.append({headers[i]: row[i] for i in range(len(headers))})
    return result


def load_csv(file_bytes):
    text = file_bytes.decode("utf-8-sig")  # strips BOM automatically
    reader = csv.DictReader(io.StringIO(text))
    return [row for row in reader]


def load_dict_file(file_bytes, filename=""):
    """Load asset dictionary — accepts both CSV and Excel."""
    name = filename.lower()
    if name.endswith(".xlsx") or name.endswith(".xlsm") or name.endswith(".xls"):
        return load_excel_sheet(file_bytes)
    return load_csv(file_bytes)


def load_linx_files(file_bytes_list):
    """Merge multiple LinX xlsx files into one list of rows, normalizing column names."""
    all_rows = []
    for fb in file_bytes_list:
        rows = load_excel_sheet(fb, sheet_name="Data")
        rows = _normalize_linx_rows(rows)
        all_rows.extend(rows)
    return all_rows


def _normalize_linx_rows(rows):
    """
    Ensure every LinX row has ASSET_ID.
    Drew's exports have ASSET_ID (e.g. ID-1234567890).
    Other exports (full LinX download) have ASSET_NAME but no ASSET_ID.
    In that case, copy ASSET_NAME -> ASSET_ID so the SQL always finds ASSET_ID.
    """
    if not rows:
        return rows
    sample = rows[0]
    has_asset_id = "ASSET_ID" in sample and sample.get("ASSET_ID") not in (None, "")
    if has_asset_id:
        return rows
    # Fallback: use ASSET_NAME as ASSET_ID
    for row in rows:
        if "ASSET_ID" not in row or not row.get("ASSET_ID"):
            row["ASSET_ID"] = row.get("ASSET_NAME", "")
    return rows


# ---------------------------------------------------------------------------
# MSL reader — reads by column index (not header name) due to known misalignment
# Col 11 = Foreseer Unique Site Prefix
# Col 18 = Full Site DNS  (header incorrectly says "Colocated Site Suffix")
# Col 40 = Longitude      (header incorrectly says "Latitude")
# Col 41 = Latitude       (header incorrectly says "Property Status")
# ---------------------------------------------------------------------------

def load_msl(file_bytes):
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True, keep_vba=False)
    ws = wb["MSL"]
    sites = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue  # skip header
        if row[5] is None:
            continue  # skip rows with no Site value
        prefix = row[11]  # Foreseer Unique Site Prefix
        full_dns = row[18]  # actual Site DNS
        lon = row[40]       # actual Longitude
        lat = row[41]       # actual Latitude
        if not prefix or not full_dns:
            continue
        # Derive short DNS: first two dot-separated segments, e.g. a1atlanta.ga
        parts = str(full_dns).strip().split(".")
        short_dns = ".".join(parts[:2]) if len(parts) >= 2 else str(full_dns).strip()
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            lat_f = lon_f = None
        sites.append({
            "site": str(row[5]).strip(),
            "prefix": str(prefix).strip(),
            "full_dns": str(full_dns).strip(),
            "short_dns": short_dns.lower(),
            "lat": lat_f,
            "lon": lon_f,
            "region": str(row[2]).strip() if row[2] else None,
            "hub_code": str(row[12]).strip() if row[12] else None,
        })
    wb.close()
    return sites


# ---------------------------------------------------------------------------
# DuckDB loader — register list-of-dicts as a relation
# ---------------------------------------------------------------------------

def register_table(con, name, rows):
    if not rows:
        # Create empty table with no columns — queries against it return nothing
        con.execute(f"CREATE TABLE {name} (dummy VARCHAR)")
        return
    df = pd.DataFrame(rows)
    # DuckDB can query a registered DataFrame directly
    con.register(name, df)


# ---------------------------------------------------------------------------
# Reconciliation SQL (DuckDB dialect)
# Parameterised by site_prefix (for Foreseer) and site_dns (for LinX)
# ---------------------------------------------------------------------------

RECON_SQL = """
WITH
params AS (
    SELECT ? AS site_dns
),

placeholders AS (
    SELECT 'TBD' AS v UNION ALL SELECT 'UNKNOWN' UNION ALL SELECT 'NA'
    UNION ALL SELECT 'N/A'        UNION ALL SELECT 'NONE'  UNION ALL SELECT '-'
    UNION ALL SELECT 'NULL'       UNION ALL SELECT 'NO VALUE'
    UNION ALL SELECT 'SELECT TO ENTER SN' UNION ALL SELECT '0'
),

dict_raw AS (
    SELECT
        lower(trim("dev prefix / mod prefix combo for lookup")) AS combo_key_norm,
        trim("Device Type Description")                         AS device_type_desc
    FROM asset_dict
    WHERE "Device Type Description" IS NOT NULL
      AND trim("Device Type Description") <> ''
      AND "dev prefix / mod prefix combo for lookup" IS NOT NULL
      AND trim("dev prefix / mod prefix combo for lookup") <> ''
),

dict_map AS (
    SELECT combo_key_norm, min(device_type_desc) AS device_type_desc_any
    FROM dict_raw
    GROUP BY combo_key_norm
),

device_types AS (
    SELECT DISTINCT device_type_desc_any AS device_type FROM dict_map
),

expected_norm AS (
    SELECT
        device_type,
        CASE
            WHEN lower(trim(device_type)) = 'transient voltage surge supression'
                THEN 'transient voltage surge suppression'
            ELSE lower(trim(device_type))
        END AS device_type_norm
    FROM device_types
),

foreseer_points AS (
    SELECT
        lower(
            regexp_replace(
                CASE
                    WHEN position('-' IN trim("Value.pointList.deviceName")) > 0
                    THEN split_part(
                            substring(
                                trim("Value.pointList.deviceName"),
                                position('-' IN trim("Value.pointList.deviceName")) + 1
                            ), '-', 1)
                    ELSE NULL
                END,
                '[0-9]', '', 'g'
            )
        ) AS combo_key_norm,

        CASE
            WHEN dm.device_type_desc_any IS NOT NULL AND trim(dm.device_type_desc_any) <> ''
            THEN CASE
                    WHEN lower(trim(dm.device_type_desc_any)) = 'transient voltage surge supression'
                        THEN 'transient voltage surge suppression'
                    ELSE lower(trim(dm.device_type_desc_any))
                 END
            ELSE CASE
                    WHEN lower(trim("Value.deviceType")) = 'transient voltage surge supression'
                        THEN 'transient voltage surge suppression'
                    ELSE lower(trim("Value.deviceType"))
                 END
        END AS device_type_norm,

        trim(coalesce(nullif(trim(dm.device_type_desc_any), ''), "Value.deviceType")) AS device_type_raw,
        lower(trim("Value.pointList.deviceName"))                                      AS device_name_norm,
        trim("Value.pointList.deviceName")                                             AS device_name_raw,
        trim("Value.pointList.pointName")                                              AS point_name,
        trim("Value.pointList.pointValue")                                             AS point_value,
        nullif(trim("Value.deviceComms.4"), '')                                        AS ip_address_raw

    FROM foreseer_data f
    JOIN params p
      ON lower(trim("Value.deviceAlarmGroupName")) LIKE '%' || lower(trim(p.site_dns)) || '%'
    LEFT JOIN dict_map dm
      ON dm.combo_key_norm = lower(
            regexp_replace(
                CASE
                    WHEN position('-' IN trim("Value.pointList.deviceName")) > 0
                    THEN split_part(
                            substring(
                                trim("Value.pointList.deviceName"),
                                position('-' IN trim("Value.pointList.deviceName")) + 1
                            ), '-', 1)
                    ELSE NULL
                END,
                '[0-9]', '', 'g'
            )
         )
    WHERE "Value.pointList.deviceName" IS NOT NULL
      AND trim("Value.pointList.deviceName") <> ''
      AND "Value.pointList.pointName" IS NOT NULL
      AND trim("Value.pointList.pointName") <> ''
),

foreseer_device_pivot AS (
    SELECT
        device_type_norm,
        device_name_norm,
        min(device_type_raw) AS device_type_any,
        min(device_name_raw) AS device_name_any,

        max(CASE WHEN lower(point_name) LIKE '%serial%'
                 THEN nullif(trim(point_value), '') ELSE NULL END) AS serial_raw,

        max(CASE WHEN ip_address_raw IS NOT NULL
                  AND trim(ip_address_raw) <> ''
                  AND trim(ip_address_raw) <> '0.0.0.0'
                  AND upper(trim(ip_address_raw)) NOT IN (SELECT v FROM placeholders)
                 THEN trim(ip_address_raw) ELSE NULL END) AS ip_from_comms,

        max(CASE WHEN lower(point_name) LIKE '%ip%'
                  AND nullif(trim(point_value), '') IS NOT NULL
                  AND trim(point_value) <> '0.0.0.0'
                  AND upper(trim(point_value)) NOT IN (SELECT v FROM placeholders)
                 THEN trim(point_value) ELSE NULL END) AS ip_from_points

    FROM foreseer_points
    GROUP BY device_type_norm, device_name_norm
),

foreseer_devices_dedup AS (
    SELECT
        device_type_norm,
        device_name_norm,
        min(device_name_any)  AS device_name_any,
        min(serial_raw)       AS serial_any,
        max(ip_from_comms)    AS comms_ip_any,
        max(ip_from_points)   AS points_ip_any,
        coalesce(max(ip_from_comms), max(ip_from_points)) AS ip_any,
        CASE WHEN coalesce(max(ip_from_comms), max(ip_from_points)) IS NULL THEN 1 ELSE 0 END
            AS foreseer_ip_missing_flag
    FROM foreseer_device_pivot
    GROUP BY device_type_norm, device_name_norm
),

foreseer_agg AS (
    SELECT
        device_type_norm,
        count(DISTINCT device_name_norm) AS foreseer_device_count,
        sum(foreseer_ip_missing_flag)    AS foreseer_missing_ip_count,

        string_agg(device_name_any || ' = ' || coalesce(ip_any, 'NO IP'),
                   ' | ' ORDER BY device_name_any) AS foreseer_asset_ip_addresses,

        string_agg(CASE
            WHEN comms_ip_any IS NOT NULL AND trim(comms_ip_any) <> ''
             AND trim(comms_ip_any) <> '0.0.0.0'
             AND upper(trim(comms_ip_any)) NOT IN (SELECT v FROM placeholders)
            THEN device_name_any ELSE NULL END,
            ', ' ORDER BY device_name_any) AS foreseer_assets_with_comms_ip

    FROM foreseer_devices_dedup
    GROUP BY device_type_norm
),

linx_base AS (
    SELECT
        CASE
            WHEN lower(trim("ASSET_SUB_TYPE")) = 'transient voltage surge supression'
                THEN 'transient voltage surge suppression'
            ELSE lower(trim("ASSET_SUB_TYPE"))
        END AS device_type_norm,
        trim("ASSET_SUB_TYPE")       AS device_type_raw,
        lower(trim("ASSET_ID"))      AS asset_id_norm,
        trim("ASSET_ID")             AS asset_id_any,
        nullif(trim("SERIAL_NUMBER"), '') AS serial_any,
        nullif(trim("IP_ADDRESS"), '')    AS ip_any,
        nullif(trim("ASSET_NAME"), '')    AS asset_name_any
    FROM linx_data l
    JOIN params p ON lower(trim(l."LOCATION")) = lower(trim(p.site_dns))
    WHERE "ASSET_ID" IS NOT NULL
      AND trim("ASSET_ID") <> ''
      AND ("PROJECT_NUMBER" IS NULL OR trim("PROJECT_NUMBER") = '')
),

linx_assets_dedup AS (
    SELECT
        device_type_norm,
        asset_id_norm,
        min(asset_id_any)   AS asset_id_any,
        min(asset_name_any) AS asset_name_any,
        max(serial_any)     AS serial_any,
        max(ip_any)         AS ip_any
    FROM linx_base
    GROUP BY device_type_norm, asset_id_norm
),

linx_agg AS (
    SELECT
        device_type_norm,
        count(*) AS linx_asset_count,

        sum(CASE
            WHEN serial_any IS NULL OR trim(serial_any) = ''             THEN 1
            WHEN upper(trim(serial_any)) LIKE 'TBD%'                     THEN 1
            WHEN upper(trim(serial_any)) IN (SELECT v FROM placeholders)  THEN 1
            ELSE 0 END) AS linx_missing_serial_count,

        sum(CASE
            WHEN ip_any IS NULL                                            THEN 1
            WHEN trim(ip_any) = '0.0.0.0'                                 THEN 1
            WHEN upper(trim(ip_any)) IN (SELECT v FROM placeholders)       THEN 1
            ELSE 0 END) AS linx_missing_ip_count,

        string_agg(asset_id_any, ', ' ORDER BY asset_id_any) AS linx_asset_ids,
        string_agg(serial_any,   ', ' ORDER BY serial_any)   AS linx_serial_numbers,

        string_agg(asset_id_any || ' = ' || CASE
                WHEN ip_any IS NULL                                        THEN 'NO IP'
                WHEN trim(ip_any) = '0.0.0.0'                             THEN 'NO IP'
                WHEN upper(trim(ip_any)) IN (SELECT v FROM placeholders)   THEN 'NO IP'
                ELSE ip_any END,
            ' | ' ORDER BY asset_id_any) AS linx_asset_ip_addresses,

        string_agg(CASE
                WHEN serial_any IS NULL OR trim(serial_any) = ''           THEN asset_id_any
                WHEN upper(trim(serial_any)) LIKE 'TBD%'                   THEN asset_id_any
                WHEN upper(trim(serial_any)) IN (SELECT v FROM placeholders) THEN asset_id_any
                ELSE NULL END,
            ', ' ORDER BY asset_id_any) AS linx_assets_missing_serial,

        string_agg(CASE
                WHEN ip_any IS NULL                                         THEN asset_id_any
                WHEN trim(ip_any) = '0.0.0.0'                              THEN asset_id_any
                WHEN upper(trim(ip_any)) IN (SELECT v FROM placeholders)    THEN asset_id_any
                ELSE NULL END,
            ', ' ORDER BY asset_id_any) AS linx_assets_missing_ip

    FROM linx_assets_dedup
    GROUP BY device_type_norm
),

foreseer_ips_by_type AS (
    SELECT DISTINCT device_type_norm, trim(ip_any) AS ip_norm
    FROM foreseer_devices_dedup
    WHERE ip_any IS NOT NULL AND trim(ip_any) <> ''
      AND trim(ip_any) <> '0.0.0.0'
      AND upper(trim(ip_any)) NOT IN (SELECT v FROM placeholders)
),

linx_ips_by_type AS (
    SELECT DISTINCT device_type_norm, trim(ip_any) AS ip_norm
    FROM linx_assets_dedup
    WHERE ip_any IS NOT NULL AND trim(ip_any) <> ''
      AND trim(ip_any) <> '0.0.0.0'
      AND upper(trim(ip_any)) NOT IN (SELECT v FROM placeholders)
),

foreseer_ips_not_in_linx AS (
    SELECT f.device_type_norm,
           count(*) AS foreseer_ip_only_count,
           string_agg(f.ip_norm, ', ' ORDER BY f.ip_norm) AS foreseer_ips_not_in_linx
    FROM foreseer_ips_by_type f
    LEFT JOIN linx_ips_by_type l
      ON f.device_type_norm = l.device_type_norm AND f.ip_norm = l.ip_norm
    WHERE l.ip_norm IS NULL
    GROUP BY f.device_type_norm
),

linx_ips_not_in_foreseer AS (
    SELECT l.device_type_norm,
           count(*) AS linx_ip_only_count,
           string_agg(l.ip_norm, ', ' ORDER BY l.ip_norm) AS linx_ips_not_in_foreseer
    FROM linx_ips_by_type l
    LEFT JOIN foreseer_ips_by_type f
      ON l.device_type_norm = f.device_type_norm AND l.ip_norm = f.ip_norm
    WHERE f.ip_norm IS NULL
    GROUP BY l.device_type_norm
),

recon AS (
    SELECT
        e.device_type, e.device_type_norm,
        coalesce(f.foreseer_device_count, 0)    AS foreseer_count,
        coalesce(l.linx_asset_count, 0)          AS linx_count,
        coalesce(f.foreseer_missing_ip_count, 0) AS foreseer_missing_ip_count,
        coalesce(l.linx_missing_serial_count, 0) AS linx_missing_serial_count,
        coalesce(l.linx_missing_ip_count, 0)     AS linx_missing_ip_count,
        coalesce(f.foreseer_device_count, 0) - coalesce(l.linx_asset_count, 0) AS count_difference,

        CASE
            WHEN greatest(coalesce(f.foreseer_device_count,0), coalesce(l.linx_asset_count,0)) = 0 THEN 0.0
            ELSE round(
                100.0 * abs(coalesce(f.foreseer_device_count,0) - coalesce(l.linx_asset_count,0))
                / greatest(coalesce(f.foreseer_device_count,0), coalesce(l.linx_asset_count,0)), 1)
        END AS pct_difference,

        f.foreseer_asset_ip_addresses,
        f.foreseer_assets_with_comms_ip,
        l.linx_asset_ids,
        l.linx_serial_numbers,
        l.linx_asset_ip_addresses,
        l.linx_assets_missing_serial,
        l.linx_assets_missing_ip,
        coalesce(fi.foreseer_ip_only_count, 0) AS foreseer_ips_not_in_linx_count,
        coalesce(li.linx_ip_only_count, 0)     AS linx_ips_not_in_foreseer_count,
        CASE WHEN coalesce(fi.foreseer_ip_only_count,0) + coalesce(li.linx_ip_only_count,0) > 0
             THEN 1 ELSE 0 END AS ip_mismatch_flag,
        fi.foreseer_ips_not_in_linx,
        li.linx_ips_not_in_foreseer

    FROM expected_norm e
    LEFT JOIN foreseer_agg f            ON e.device_type_norm = f.device_type_norm
    LEFT JOIN linx_agg l                ON e.device_type_norm = l.device_type_norm
    LEFT JOIN foreseer_ips_not_in_linx fi ON e.device_type_norm = fi.device_type_norm
    LEFT JOIN linx_ips_not_in_foreseer li ON e.device_type_norm = li.device_type_norm
),

scored AS (
    SELECT r.*,
        CASE
            WHEN foreseer_count = 0 AND linx_count = 0 THEN 'No records in either system'
            WHEN foreseer_count = 0 AND linx_count > 0 THEN 'Present in LinX, Missing in Foreseer'
            WHEN linx_count = 0 AND foreseer_count > 0 THEN 'Present in Foreseer, Missing in LinX'
            WHEN pct_difference = 0
             AND linx_missing_serial_count = 0
             AND linx_missing_ip_count = 0
             AND foreseer_missing_ip_count = 0
             AND ip_mismatch_flag = 0
            THEN 'Match'
            ELSE 'Mismatch / Needs review'
        END AS match_status,

        CASE
            WHEN foreseer_count = 0 AND linx_count = 0 THEN 0
            ELSE greatest(0,
                100
                - least(60, cast(round(pct_difference) AS integer))
                - CASE WHEN linx_missing_serial_count > 0 THEN 10 ELSE 0 END
                - CASE WHEN (linx_missing_ip_count + foreseer_missing_ip_count) > 0 THEN 10 ELSE 0 END
                - CASE WHEN ip_mismatch_flag > 0 THEN 10 ELSE 0 END
            )
        END AS match_score,

        concat_ws('; ',
            CASE WHEN pct_difference > 0
                 THEN 'Count mismatch (' || pct_difference || '%)' ELSE NULL END,
            CASE WHEN linx_missing_serial_count > 0
                 THEN 'LinX missing serials: ' || linx_missing_serial_count ELSE NULL END,
            CASE WHEN linx_missing_ip_count > 0
                 THEN 'LinX missing/placeholder IPs: ' || linx_missing_ip_count ELSE NULL END,
            CASE WHEN foreseer_missing_ip_count > 0
                 THEN 'Foreseer missing/placeholder IPs: ' || foreseer_missing_ip_count ELSE NULL END,
            CASE WHEN foreseer_ips_not_in_linx_count > 0
                 THEN 'Foreseer IPs not in LinX: ' || foreseer_ips_not_in_linx_count ELSE NULL END,
            CASE WHEN linx_ips_not_in_foreseer_count > 0
                 THEN 'LinX IPs not in Foreseer: ' || linx_ips_not_in_foreseer_count ELSE NULL END
        ) AS notes
    FROM recon r
),

totals AS (
    SELECT
        'TOTAL_ASSETS_ALL_TYPES' AS device_type,
        (SELECT count(DISTINCT device_name_norm) FROM foreseer_devices_dedup) AS foreseer_count,
        (SELECT count(*) FROM linx_assets_dedup)                              AS linx_count,
        (SELECT sum(foreseer_ip_missing_flag) FROM foreseer_devices_dedup)    AS foreseer_missing_ip_count,
        (SELECT sum(CASE
            WHEN serial_any IS NULL OR trim(serial_any) = ''             THEN 1
            WHEN upper(trim(serial_any)) LIKE 'TBD%'                     THEN 1
            WHEN upper(trim(serial_any)) IN (SELECT v FROM placeholders)  THEN 1
            ELSE 0 END) FROM linx_assets_dedup)                               AS linx_missing_serial_count,
        (SELECT sum(CASE
            WHEN ip_any IS NULL                                            THEN 1
            WHEN trim(ip_any) = '0.0.0.0'                                 THEN 1
            WHEN upper(trim(ip_any)) IN (SELECT v FROM placeholders)       THEN 1
            ELSE 0 END) FROM linx_assets_dedup)                               AS linx_missing_ip_count,
        (SELECT count(DISTINCT device_name_norm) FROM foreseer_devices_dedup)
        - (SELECT count(*) FROM linx_assets_dedup)                            AS count_difference,
        CASE
            WHEN greatest(
                (SELECT count(DISTINCT device_name_norm) FROM foreseer_devices_dedup),
                (SELECT count(*) FROM linx_assets_dedup)) = 0 THEN 0.0
            ELSE round(100.0 * abs(
                (SELECT count(DISTINCT device_name_norm) FROM foreseer_devices_dedup)
                - (SELECT count(*) FROM linx_assets_dedup))
                / greatest(
                    (SELECT count(DISTINCT device_name_norm) FROM foreseer_devices_dedup),
                    (SELECT count(*) FROM linx_assets_dedup)), 1)
        END AS pct_difference,
        (SELECT coalesce(sum(foreseer_ip_only_count), 0) FROM foreseer_ips_not_in_linx) AS foreseer_ips_not_in_linx_count,
        (SELECT coalesce(sum(linx_ip_only_count), 0)     FROM linx_ips_not_in_foreseer) AS linx_ips_not_in_foreseer_count
)

SELECT * FROM (
    SELECT
        device_type, foreseer_count, linx_count, count_difference, pct_difference,
        foreseer_missing_ip_count, linx_missing_serial_count, linx_missing_ip_count,
        foreseer_ips_not_in_linx_count, linx_ips_not_in_foreseer_count,
        ip_mismatch_flag, match_status, match_score, notes,
        foreseer_asset_ip_addresses, foreseer_assets_with_comms_ip,
        linx_asset_ids, linx_serial_numbers, linx_asset_ip_addresses,
        linx_assets_missing_serial, linx_assets_missing_ip,
        foreseer_ips_not_in_linx, linx_ips_not_in_foreseer
    FROM scored
    UNION ALL
    SELECT
        device_type, foreseer_count, linx_count, count_difference, pct_difference,
        foreseer_missing_ip_count, linx_missing_serial_count, linx_missing_ip_count,
        foreseer_ips_not_in_linx_count, linx_ips_not_in_foreseer_count,
        CASE WHEN foreseer_ips_not_in_linx_count + linx_ips_not_in_foreseer_count > 0 THEN 1 ELSE 0 END,
        NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL
    FROM totals
) final_results
ORDER BY
    CASE WHEN device_type = 'TOTAL_ASSETS_ALL_TYPES' THEN 1 ELSE 0 END,
    abs(count_difference) DESC,
    device_type
"""

# ---------------------------------------------------------------------------
# Asset-level pairing query
# Matches individual Foreseer devices to LinX assets within the same device type
# Match priority: IP match > Serial match > Name match > Unmatched
# ---------------------------------------------------------------------------

ASSET_PAIRING_SQL = """
WITH
params AS (SELECT ? AS site_dns),

placeholders AS (
    SELECT 'TBD' AS v UNION ALL SELECT 'UNKNOWN' UNION ALL SELECT 'NA'
    UNION ALL SELECT 'N/A' UNION ALL SELECT 'NONE' UNION ALL SELECT '-'
    UNION ALL SELECT 'NULL' UNION ALL SELECT 'NO VALUE'
    UNION ALL SELECT 'SELECT TO ENTER SN' UNION ALL SELECT '0'
),

dict_raw AS (
    SELECT
        lower(trim("dev prefix / mod prefix combo for lookup")) AS combo_key_norm,
        trim("Device Type Description") AS device_type_desc
    FROM asset_dict
    WHERE "Device Type Description" IS NOT NULL AND trim("Device Type Description") <> ''
      AND "dev prefix / mod prefix combo for lookup" IS NOT NULL
      AND trim("dev prefix / mod prefix combo for lookup") <> ''
),
dict_map AS (
    SELECT combo_key_norm, min(device_type_desc) AS device_type_desc_any
    FROM dict_raw GROUP BY combo_key_norm
),

-- Foreseer: one row per unique device with its type, IP, and serial
foreseer_devices AS (
    SELECT
        CASE
            WHEN dm.device_type_desc_any IS NOT NULL AND trim(dm.device_type_desc_any) <> ''
            THEN CASE WHEN lower(trim(dm.device_type_desc_any)) = 'transient voltage surge supression'
                      THEN 'transient voltage surge suppression'
                      ELSE lower(trim(dm.device_type_desc_any)) END
            ELSE lower(trim(f."Value.deviceType"))
        END AS device_type_norm,
        lower(trim(f."Value.pointList.deviceName")) AS device_name_norm,
        trim(f."Value.pointList.deviceName")         AS device_name,
        -- Best IP: comms channel first, then point value
        max(CASE WHEN lower(trim(f."Value.pointList.pointName")) LIKE '%ip%'
                  AND nullif(trim(f."Value.pointList.pointValue"), '') IS NOT NULL
                  AND trim(f."Value.pointList.pointValue") <> '0.0.0.0'
                  AND upper(trim(f."Value.pointList.pointValue")) NOT IN (SELECT v FROM placeholders)
                 THEN trim(f."Value.pointList.pointValue") ELSE NULL END) AS foreseer_ip,
        max(CASE WHEN nullif(trim(f."Value.deviceComms.4"), '') IS NOT NULL
                  AND trim(f."Value.deviceComms.4") <> '0.0.0.0'
                  AND upper(trim(f."Value.deviceComms.4")) NOT IN (SELECT v FROM placeholders)
                 THEN trim(f."Value.deviceComms.4") ELSE NULL END) AS foreseer_comms_ip,
        max(CASE WHEN lower(trim(f."Value.pointList.pointName")) LIKE '%serial%'
                 THEN nullif(trim(f."Value.pointList.pointValue"), '') ELSE NULL END) AS foreseer_serial
    FROM foreseer_data f
    LEFT JOIN dict_map dm ON dm.combo_key_norm = lower(regexp_replace(
        CASE WHEN position('-' IN trim(f."Value.pointList.deviceName")) > 0
             THEN split_part(substring(trim(f."Value.pointList.deviceName"),
                  position('-' IN trim(f."Value.pointList.deviceName")) + 1), '-', 1)
             ELSE NULL END, '[0-9]', '', 'g'))
    WHERE lower(trim(f."Value.deviceAlarmGroupName")) LIKE '%' || lower(trim((SELECT site_dns FROM params))) || '%'
      AND f."Value.pointList.deviceName" IS NOT NULL
      AND trim(f."Value.pointList.deviceName") <> ''
    GROUP BY 1, 2, 3
),

foreseer_dedup AS (
    SELECT
        device_type_norm, device_name_norm, device_name,
        coalesce(foreseer_comms_ip, foreseer_ip) AS foreseer_ip,
        foreseer_serial
    FROM foreseer_devices
    GROUP BY 1, 2, 3, 4, 5
),

-- LinX: one row per unique asset
linx_assets AS (
    SELECT
        CASE WHEN lower(trim(l."ASSET_SUB_TYPE")) = 'transient voltage surge supression'
             THEN 'transient voltage surge suppression'
             ELSE lower(trim(l."ASSET_SUB_TYPE")) END AS device_type_norm,
        lower(trim(l."ASSET_ID"))    AS asset_id_norm,
        trim(l."ASSET_ID")           AS asset_id,
        trim(l."ASSET_NAME")         AS asset_name,
        CASE WHEN l."SERIAL_NUMBER" IS NOT NULL
              AND trim(l."SERIAL_NUMBER") <> ''
              AND upper(trim(l."SERIAL_NUMBER")) NOT IN (SELECT v FROM placeholders)
              AND upper(trim(l."SERIAL_NUMBER")) NOT LIKE 'TBD%'
             THEN trim(l."SERIAL_NUMBER") ELSE NULL END AS linx_serial,
        CASE WHEN l."IP_ADDRESS" IS NOT NULL
              AND trim(l."IP_ADDRESS") <> ''
              AND trim(l."IP_ADDRESS") <> '0.0.0.0'
              AND upper(trim(l."IP_ADDRESS")) NOT IN (SELECT v FROM placeholders)
             THEN trim(l."IP_ADDRESS") ELSE NULL END AS linx_ip
    FROM linx_data l
    JOIN params p ON lower(trim(l."LOCATION")) = lower(trim(p.site_dns))
    WHERE l."ASSET_ID" IS NOT NULL AND trim(l."ASSET_ID") <> ''
      AND (l."PROJECT_NUMBER" IS NULL OR trim(l."PROJECT_NUMBER") = '')
),

-- IP-based matches (strongest signal)
ip_matches AS (
    SELECT
        f.device_type_norm,
        f.device_name,
        f.foreseer_ip,
        f.foreseer_serial,
        l.asset_id,
        l.asset_name,
        l.linx_ip,
        l.linx_serial,
        'IP Match' AS match_method
    FROM foreseer_dedup f
    JOIN linx_assets l
      ON f.device_type_norm = l.device_type_norm
     AND f.foreseer_ip IS NOT NULL
     AND l.linx_ip IS NOT NULL
     AND trim(f.foreseer_ip) = trim(l.linx_ip)
),

-- Serial-based matches (for assets without IP match)
serial_matches AS (
    SELECT
        f.device_type_norm,
        f.device_name,
        f.foreseer_ip,
        f.foreseer_serial,
        l.asset_id,
        l.asset_name,
        l.linx_ip,
        l.linx_serial,
        'Serial Match' AS match_method
    FROM foreseer_dedup f
    JOIN linx_assets l
      ON f.device_type_norm = l.device_type_norm
     AND f.foreseer_serial IS NOT NULL
     AND l.linx_serial IS NOT NULL
     AND upper(trim(f.foreseer_serial)) = upper(trim(l.linx_serial))
    -- exclude anything already matched by IP
    WHERE NOT EXISTS (
        SELECT 1 FROM ip_matches m
        WHERE m.device_name = f.device_name AND m.asset_id = l.asset_id
    )
),

-- Name-based matches: strip hub prefix from both sides, compare base device identifier
-- Foreseer: FLVBEA9401-GEN01  -> everything after first dash -> GEN01
-- LinX:     FLVB-GEN01        -> ASSET_NAME after first dash -> GEN01
name_matches AS (
    SELECT
        f.device_type_norm,
        f.device_name,
        f.foreseer_ip,
        f.foreseer_serial,
        l.asset_id,
        l.asset_name,
        l.linx_ip,
        l.linx_serial,
        'Name Match' AS match_method
    FROM foreseer_dedup f
    JOIN linx_assets l
      ON f.device_type_norm = l.device_type_norm
     -- compare the portion after the first dash (the base device name)
     AND position('-' IN f.device_name) > 0
     AND position('-' IN lower(coalesce(l.asset_name, l.asset_id))) > 0
     AND lower(substring(f.device_name, position('-' IN f.device_name) + 1))
         = lower(substring(coalesce(l.asset_name, l.asset_id),
                 position('-' IN lower(coalesce(l.asset_name, l.asset_id))) + 1))
    WHERE NOT EXISTS (
        SELECT 1 FROM ip_matches     m WHERE m.device_name = f.device_name
    )
    AND NOT EXISTS (
        SELECT 1 FROM serial_matches m WHERE m.device_name = f.device_name
    )
    AND NOT EXISTS (
        SELECT 1 FROM ip_matches     m WHERE m.asset_id = l.asset_id
    )
    AND NOT EXISTS (
        SELECT 1 FROM serial_matches m WHERE m.asset_id = l.asset_id
    )
),

all_matched AS (
    SELECT * FROM ip_matches
    UNION ALL
    SELECT * FROM serial_matches
    UNION ALL
    SELECT * FROM name_matches
),

-- Foreseer devices with no match in LinX
foreseer_unmatched AS (
    SELECT
        f.device_type_norm,
        f.device_name,
        f.foreseer_ip,
        f.foreseer_serial,
        NULL AS asset_id,
        NULL AS asset_name,
        NULL AS linx_ip,
        NULL AS linx_serial,
        'Foreseer Only' AS match_method
    FROM foreseer_dedup f
    WHERE NOT EXISTS (
        SELECT 1 FROM all_matched m WHERE m.device_name = f.device_name
    )
),

-- LinX assets with no match in Foreseer
linx_unmatched AS (
    SELECT
        l.device_type_norm,
        NULL AS device_name,
        NULL AS foreseer_ip,
        NULL AS foreseer_serial,
        l.asset_id,
        l.asset_name,
        l.linx_ip,
        l.linx_serial,
        'LinX Only' AS match_method
    FROM linx_assets l
    WHERE NOT EXISTS (
        SELECT 1 FROM all_matched m WHERE m.asset_id = l.asset_id
    )
)

SELECT
    device_type_norm AS device_type,
    match_method,
    device_name      AS foreseer_device,
    foreseer_ip,
    foreseer_serial,
    asset_id         AS linx_asset_id,
    asset_name       AS linx_asset_name,
    linx_ip,
    linx_serial
FROM (
    SELECT * FROM all_matched
    UNION ALL
    SELECT * FROM foreseer_unmatched
    UNION ALL
    SELECT * FROM linx_unmatched
) combined
ORDER BY device_type_norm, match_method, foreseer_device, linx_asset_id
"""

# Prefix resolution trace — for the review tab
PREFIX_TRACE_SQL = """
WITH
dict_raw AS (
    SELECT
        lower(trim("dev prefix / mod prefix combo for lookup")) AS combo_key_norm,
        trim("Device Type Description") AS device_type_desc
    FROM asset_dict
    WHERE "Device Type Description" IS NOT NULL AND trim("Device Type Description") <> ''
      AND "dev prefix / mod prefix combo for lookup" IS NOT NULL
      AND trim("dev prefix / mod prefix combo for lookup") <> ''
),
dict_map AS (
    SELECT combo_key_norm, min(device_type_desc) AS device_type_desc_any
    FROM dict_raw GROUP BY combo_key_norm
)
SELECT
    trim("Value.pointList.deviceName") AS device_name,
    CASE
        WHEN position('-' IN trim("Value.pointList.deviceName")) > 0
        THEN split_part(
            substring(trim("Value.pointList.deviceName"),
                      position('-' IN trim("Value.pointList.deviceName")) + 1),
            '-', 1)
        ELSE NULL
    END AS hub_stripped,
    lower(regexp_replace(
        CASE
            WHEN position('-' IN trim("Value.pointList.deviceName")) > 0
            THEN split_part(
                substring(trim("Value.pointList.deviceName"),
                          position('-' IN trim("Value.pointList.deviceName")) + 1),
                '-', 1)
            ELSE NULL
        END, '[0-9]', '', 'g')) AS combo_key_derived,
    dm.device_type_desc_any AS resolved_type,
    CASE WHEN dm.device_type_desc_any IS NOT NULL THEN 'Matched' ELSE 'No match' END AS status
FROM foreseer_data f
LEFT JOIN dict_map dm ON dm.combo_key_norm = lower(regexp_replace(
    CASE
        WHEN position('-' IN trim("Value.pointList.deviceName")) > 0
        THEN split_part(
            substring(trim("Value.pointList.deviceName"),
                      position('-' IN trim("Value.pointList.deviceName")) + 1),
            '-', 1)
        ELSE NULL
    END, '[0-9]', '', 'g'))
WHERE lower(trim("Value.deviceAlarmGroupName")) LIKE '%' || lower(trim(?)) || '%'
  AND "Value.pointList.deviceName" IS NOT NULL
  AND trim("Value.pointList.deviceName") <> ''
GROUP BY 1, 2, 3, 4, 5
ORDER BY status DESC, device_name
"""


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------

def run_reconciliation(foreseer_bytes, linx_bytes_list, dict_bytes, msl_sites, dict_filename=""):
    print("Loading files into memory...")
    foreseer_rows = load_excel_sheet(foreseer_bytes, sheet_name="Result Data")
    linx_rows     = load_linx_files(linx_bytes_list)
    dict_rows     = load_dict_file(dict_bytes, dict_filename)

    # Determine sites from LinX LOCATION column
    linx_locations = sorted({str(r.get("LOCATION", "")).strip().lower()
                              for r in linx_rows if r.get("LOCATION")})
    print(f"Found {len(linx_locations)} sites in LinX, {len(foreseer_rows)} Foreseer rows, {len(linx_rows)} LinX rows")

    # Create ONE connection and register tables once — massive speedup for multi-site
    con = duckdb.connect()
    try:
        register_table(con, "foreseer_data", foreseer_rows)
        register_table(con, "linx_data",     linx_rows)
        register_table(con, "asset_dict",    dict_rows)

        results_by_site = {}
        for i, loc in enumerate(linx_locations):
            print(f"  [{i+1}/{len(linx_locations)}] Processing {loc}...")
            msl_entry = next((s for s in msl_sites if s["short_dns"] == loc), None)

            try:
                # Core reconciliation — always run
                recon_rows = con.execute(RECON_SQL, [loc]).fetchall()
                recon_cols = [d[0] for d in con.description]

                total_foreseer = con.execute(
                    'SELECT count(*) FROM foreseer_data WHERE lower(trim("Value.deviceAlarmGroupName")) LIKE \'%\' || lower(trim(?)) || \'%\'',
                    [loc]
                ).fetchone()[0]
                total_linx_raw = con.execute(
                    "SELECT count(*) FROM linx_data WHERE lower(trim(\"LOCATION\")) = lower(?)", [loc]
                ).fetchone()[0]
                total_linx_filtered = con.execute(
                    "SELECT count(*) FROM linx_data WHERE lower(trim(\"LOCATION\")) = lower(?) AND (\"PROJECT_NUMBER\" IS NULL OR trim(\"PROJECT_NUMBER\") = '')",
                    [loc]
                ).fetchone()[0]

                # Prefix trace + asset pairing are loaded on-demand per site (not in batch)
                # They are fetched via /api/site-detail when a user clicks a site
                results_by_site[loc] = {
                    "site_dns":   loc,
                    "msl_info":   msl_entry,
                    "sanity": {
                        "foreseer_raw_rows":         total_foreseer,
                        "linx_raw_rows":             total_linx_raw,
                        "linx_after_project_filter": total_linx_filtered,
                        "dict_entries":              len(dict_rows),
                    },
                    "reconciliation": [dict(zip(recon_cols, r)) for r in recon_rows],
                    "prefix_trace":   [],   # loaded on demand
                    "asset_pairs":    [],   # loaded on demand
                }
            except Exception as e:
                print(f"    ERROR on {loc}: {e}")
                results_by_site[loc] = {"site_dns": loc, "error": str(e), "reconciliation": [], "prefix_trace": [], "asset_pairs": []}

    finally:
        con.close()

    print(f"Done. {len(results_by_site)} sites processed.")
    return results_by_site


def run_site_detail(foreseer_bytes, linx_bytes_list, dict_bytes, site_dns, dict_filename=""):
    """Load prefix trace + asset pairs for a single site on demand."""
    foreseer_rows = load_excel_sheet(foreseer_bytes, sheet_name="Result Data")
    linx_rows     = load_linx_files(linx_bytes_list)
    dict_rows     = load_dict_file(dict_bytes, dict_filename)

    con = duckdb.connect()
    try:
        register_table(con, "foreseer_data", foreseer_rows)
        register_table(con, "linx_data",     linx_rows)
        register_table(con, "asset_dict",    dict_rows)

        trace_rows = con.execute(PREFIX_TRACE_SQL, [site_dns]).fetchall()
        trace_cols = [d[0] for d in con.description]

        pair_rows = con.execute(ASSET_PAIRING_SQL, [site_dns]).fetchall()
        pair_cols = [d[0] for d in con.description]

        return {
            "prefix_trace": [dict(zip(trace_cols, r)) for r in trace_rows],
            "asset_pairs":  [dict(zip(pair_cols,  r)) for r in pair_rows],
        }
    finally:
        con.close()


def _infer_prefix_from_location(loc, foreseer_rows):
    """
    Fallback: find device names in Foreseer whose location fuzzy-matches loc,
    then return the most common prefix. Used when MSL has no entry for the site.
    """
    loc_clean = loc.replace(".", "").replace(" ", "").replace(",", "").lower()
    candidates = []
    for r in foreseer_rows:
        dev_loc = str(r.get("Value.deviceLocation", "") or "").replace(".", "").replace(" ", "").replace(",", "").lower()
        dev_name = str(r.get("Value.pointList.deviceName", "") or "").strip()
        if loc_clean in dev_loc and "-" in dev_name:
            candidates.append(dev_name.split("-")[0].upper())
    if not candidates:
        return None
    return max(set(candidates), key=candidates.count)


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def lambda_handler(event, context):
    try:
        body = json.loads(event.get("body", "{}"))
        foreseer_key = body.get("foreseer_key")
        linx_keys    = body.get("linx_keys", [])
        dict_key     = body.get("dict_key")

        if not foreseer_key or not linx_keys or not dict_key:
            return _resp(400, {"error": "Missing required keys: foreseer_key, linx_keys, dict_key"})

        foreseer_bytes   = s3.get_object(Bucket=BUCKET, Key=foreseer_key)["Body"].read()
        linx_bytes_list  = [s3.get_object(Bucket=BUCKET, Key=k)["Body"].read() for k in linx_keys]
        dict_bytes       = s3.get_object(Bucket=BUCKET, Key=dict_key)["Body"].read()

        # Load MSL from Foreseer file
        msl_sites = load_msl(foreseer_bytes)

        results = run_reconciliation(foreseer_bytes, linx_bytes_list, dict_bytes, msl_sites)

        return _resp(200, {
            "status": "ok",
            "sites_processed": list(results.keys()),
            "results": results,
            "msl_sites": msl_sites,
        })

    except Exception as e:
        import traceback
        return _resp(500, {"error": str(e), "trace": traceback.format_exc()})


def _resp(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }
