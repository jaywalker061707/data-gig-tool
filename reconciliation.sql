-- DuckDB dialect reconciliation query
-- Table names (set by Lambda at load time):
--   foreseer_data   : the raw Foreseer sheet
--   linx_data       : all LinX files merged, one row per asset
--   asset_dict      : Asset Type Dictionary CSV

WITH
params AS (
    SELECT ? AS site_dns          -- bound at runtime per site
),

placeholders AS (
    SELECT 'TBD' AS v UNION ALL SELECT 'UNKNOWN' UNION ALL SELECT 'NA'
    UNION ALL SELECT 'N/A'        UNION ALL SELECT 'NONE'  UNION ALL SELECT '-'
    UNION ALL SELECT 'NULL'       UNION ALL SELECT 'NO VALUE'
    UNION ALL SELECT 'SELECT TO ENTER SN' UNION ALL SELECT '0'
),

dict_raw AS (
    SELECT
        lower(trim(d."dev prefix / mod prefix combo for lookup")) AS combo_key_norm,
        trim(d."Device Type Description")                         AS device_type_desc
    FROM asset_dict d
    WHERE d."Device Type Description" IS NOT NULL
      AND trim(d."Device Type Description") <> ''
      AND d."dev prefix / mod prefix combo for lookup" IS NOT NULL
      AND trim(d."dev prefix / mod prefix combo for lookup") <> ''
),

dict_map AS (
    SELECT
        combo_key_norm,
        min(device_type_desc) AS device_type_desc_any
    FROM dict_raw
    GROUP BY combo_key_norm
),

device_types AS (
    SELECT DISTINCT device_type_desc_any AS device_type
    FROM dict_map
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
        -- strip hub prefix (everything before first '-'), then strip digits
        lower(
            regexp_replace(
                CASE
                    WHEN position('-' IN trim(f."Value.pointList.deviceName")) > 0
                    THEN split_part(
                            substring(
                                trim(f."Value.pointList.deviceName"),
                                position('-' IN trim(f."Value.pointList.deviceName")) + 1
                            ),
                            '-', 1
                         )
                    ELSE NULL
                END,
                '[0-9]', '', 'g'
            )
        ) AS combo_key_norm,

        CASE
            WHEN dm.device_type_desc_any IS NOT NULL
             AND trim(dm.device_type_desc_any) <> ''
            THEN CASE
                    WHEN lower(trim(dm.device_type_desc_any)) = 'transient voltage surge supression'
                        THEN 'transient voltage surge suppression'
                    ELSE lower(trim(dm.device_type_desc_any))
                 END
            ELSE CASE
                    WHEN lower(trim(f."DeviceType")) = 'transient voltage surge supression'
                        THEN 'transient voltage surge suppression'
                    ELSE lower(trim(f."DeviceType"))
                 END
        END AS device_type_norm,

        trim(coalesce(nullif(trim(dm.device_type_desc_any), ''), f."DeviceType")) AS device_type_raw,
        lower(trim(f."Value.pointList.deviceName"))                               AS device_name_norm,
        trim(f."Value.pointList.deviceName")                                      AS device_name_raw,
        trim(f."Value.pointList.pointName")                                       AS point_name,
        trim(f."Value.pointList.pointValue")                                      AS point_value,
        nullif(trim(f."Value.deviceComms.4"), '')                                 AS ip_address_raw

    FROM foreseer_data f
    JOIN params p
      ON lower(replace(replace(replace(trim(f."Value.deviceLocation"), '.', ''), ' ', ''), ',', ''))
         LIKE '%' || lower(replace(replace(replace(trim(p.site_dns), '.', ''), ' ', ''), ',', '')) || '%'
    LEFT JOIN dict_map dm
      ON dm.combo_key_norm = lower(
            regexp_replace(
                CASE
                    WHEN position('-' IN trim(f."Value.pointList.deviceName")) > 0
                    THEN split_part(
                            substring(
                                trim(f."Value.pointList.deviceName"),
                                position('-' IN trim(f."Value.pointList.deviceName")) + 1
                            ),
                            '-', 1
                         )
                    ELSE NULL
                END,
                '[0-9]', '', 'g'
            )
         )
    WHERE f."Value.pointList.deviceName" IS NOT NULL
      AND trim(f."Value.pointList.deviceName") <> ''
      AND f."Value.pointList.pointName" IS NOT NULL
      AND trim(f."Value.pointList.pointName") <> ''
),

foreseer_device_pivot AS (
    SELECT
        device_type_norm,
        device_name_norm,
        min(device_type_raw)  AS device_type_any,
        min(device_name_raw)  AS device_name_any,

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

        string_agg(
            DISTINCT device_name_any || ' = ' || coalesce(ip_any, 'NO IP'),
            ' | ' ORDER BY device_name_any
        ) AS foreseer_asset_ip_addresses,

        string_agg(
            DISTINCT CASE
                WHEN comms_ip_any IS NOT NULL
                 AND trim(comms_ip_any) <> ''
                 AND trim(comms_ip_any) <> '0.0.0.0'
                 AND upper(trim(comms_ip_any)) NOT IN (SELECT v FROM placeholders)
                THEN device_name_any ELSE NULL END,
            ', ' ORDER BY device_name_any
        ) AS foreseer_assets_with_comms_ip

    FROM foreseer_devices_dedup
    GROUP BY device_type_norm
),

linx_base AS (
    SELECT
        CASE
            WHEN lower(trim(l."ASSET_SUB_TYPE")) = 'transient voltage surge supression'
                THEN 'transient voltage surge suppression'
            ELSE lower(trim(l."ASSET_SUB_TYPE"))
        END AS device_type_norm,
        trim(l."ASSET_SUB_TYPE")      AS device_type_raw,
        lower(trim(l."ASSET_ID"))     AS asset_id_norm,
        trim(l."ASSET_ID")            AS asset_id_any,
        nullif(trim(l."SERIAL_NUMBER"), '') AS serial_any,
        nullif(trim(l."IP_ADDRESS"), '')    AS ip_any,   -- Lambda strips BOM from header
        nullif(trim(l."ASSET_NAME"), '')    AS asset_name_any
    FROM linx_data l
    JOIN params p
      ON lower(trim(l."LOCATION")) = lower(trim(p.site_dns))
    WHERE l."ASSET_ID" IS NOT NULL
      AND trim(l."ASSET_ID") <> ''
      AND (l."PROJECT_NUMBER" IS NULL OR trim(l."PROJECT_NUMBER") = '')
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
        count(*)  AS linx_asset_count,

        sum(CASE
            WHEN serial_any IS NULL OR trim(serial_any) = ''              THEN 1
            WHEN upper(trim(serial_any)) LIKE 'TBD%'                      THEN 1
            WHEN upper(trim(serial_any)) IN (SELECT v FROM placeholders)   THEN 1
            ELSE 0 END) AS linx_missing_serial_count,

        sum(CASE
            WHEN ip_any IS NULL                                             THEN 1
            WHEN trim(ip_any) = '0.0.0.0'                                  THEN 1
            WHEN upper(trim(ip_any)) IN (SELECT v FROM placeholders)        THEN 1
            ELSE 0 END) AS linx_missing_ip_count,

        string_agg(DISTINCT asset_id_any, ', ' ORDER BY asset_id_any) AS linx_asset_ids,
        string_agg(DISTINCT serial_any,   ', ' ORDER BY serial_any)   AS linx_serial_numbers,

        string_agg(
            DISTINCT asset_id_any || ' = ' || CASE
                WHEN ip_any IS NULL                                          THEN 'NO IP'
                WHEN trim(ip_any) = '0.0.0.0'                               THEN 'NO IP'
                WHEN upper(trim(ip_any)) IN (SELECT v FROM placeholders)     THEN 'NO IP'
                ELSE ip_any END,
            ' | ' ORDER BY asset_id_any
        ) AS linx_asset_ip_addresses,

        string_agg(
            DISTINCT CASE
                WHEN serial_any IS NULL OR trim(serial_any) = ''             THEN asset_id_any
                WHEN upper(trim(serial_any)) LIKE 'TBD%'                     THEN asset_id_any
                WHEN upper(trim(serial_any)) IN (SELECT v FROM placeholders)  THEN asset_id_any
                ELSE NULL END,
            ', ' ORDER BY asset_id_any
        ) AS linx_assets_missing_serial,

        string_agg(
            DISTINCT CASE
                WHEN ip_any IS NULL                                            THEN asset_id_any
                WHEN trim(ip_any) = '0.0.0.0'                                 THEN asset_id_any
                WHEN upper(trim(ip_any)) IN (SELECT v FROM placeholders)       THEN asset_id_any
                ELSE NULL END,
            ', ' ORDER BY asset_id_any
        ) AS linx_assets_missing_ip

    FROM linx_assets_dedup
    GROUP BY device_type_norm
),

foreseer_ips_by_type AS (
    SELECT DISTINCT device_type_norm, trim(ip_any) AS ip_norm
    FROM foreseer_devices_dedup
    WHERE ip_any IS NOT NULL
      AND trim(ip_any) <> ''
      AND trim(ip_any) <> '0.0.0.0'
      AND upper(trim(ip_any)) NOT IN (SELECT v FROM placeholders)
),

linx_ips_by_type AS (
    SELECT DISTINCT device_type_norm, trim(ip_any) AS ip_norm
    FROM linx_assets_dedup
    WHERE ip_any IS NOT NULL
      AND trim(ip_any) <> ''
      AND trim(ip_any) <> '0.0.0.0'
      AND upper(trim(ip_any)) NOT IN (SELECT v FROM placeholders)
),

foreseer_ips_not_in_linx AS (
    SELECT
        f.device_type_norm,
        count(*)                                              AS foreseer_ip_only_count,
        string_agg(f.ip_norm, ', ' ORDER BY f.ip_norm)       AS foreseer_ips_not_in_linx
    FROM foreseer_ips_by_type f
    LEFT JOIN linx_ips_by_type l
      ON f.device_type_norm = l.device_type_norm AND f.ip_norm = l.ip_norm
    WHERE l.ip_norm IS NULL
    GROUP BY f.device_type_norm
),

linx_ips_not_in_foreseer AS (
    SELECT
        l.device_type_norm,
        count(*)                                              AS linx_ip_only_count,
        string_agg(l.ip_norm, ', ' ORDER BY l.ip_norm)       AS linx_ips_not_in_foreseer
    FROM linx_ips_by_type l
    LEFT JOIN foreseer_ips_by_type f
      ON l.device_type_norm = f.device_type_norm AND l.ip_norm = f.ip_norm
    WHERE f.ip_norm IS NULL
    GROUP BY l.device_type_norm
),

recon AS (
    SELECT
        e.device_type,
        e.device_type_norm,
        coalesce(f.foreseer_device_count, 0)    AS foreseer_count,
        coalesce(l.linx_asset_count, 0)          AS linx_count,
        coalesce(f.foreseer_missing_ip_count, 0) AS foreseer_missing_ip_count,
        coalesce(l.linx_missing_serial_count, 0) AS linx_missing_serial_count,
        coalesce(l.linx_missing_ip_count, 0)     AS linx_missing_ip_count,
        coalesce(f.foreseer_device_count, 0) - coalesce(l.linx_asset_count, 0) AS count_difference,

        CASE
            WHEN greatest(coalesce(f.foreseer_device_count, 0), coalesce(l.linx_asset_count, 0)) = 0 THEN 0
            ELSE round(
                100.0 * abs(coalesce(f.foreseer_device_count, 0) - coalesce(l.linx_asset_count, 0))
                / greatest(coalesce(f.foreseer_device_count, 0), coalesce(l.linx_asset_count, 0)),
                1
            )
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
        CASE WHEN coalesce(fi.foreseer_ip_only_count, 0) + coalesce(li.linx_ip_only_count, 0) > 0
             THEN 1 ELSE 0 END                 AS ip_mismatch_flag,
        fi.foreseer_ips_not_in_linx,
        li.linx_ips_not_in_foreseer

    FROM expected_norm e
    LEFT JOIN foreseer_agg f            ON e.device_type_norm = f.device_type_norm
    LEFT JOIN linx_agg l                ON e.device_type_norm = l.device_type_norm
    LEFT JOIN foreseer_ips_not_in_linx fi ON e.device_type_norm = fi.device_type_norm
    LEFT JOIN linx_ips_not_in_foreseer li ON e.device_type_norm = li.device_type_norm
),

scored AS (
    SELECT
        r.*,

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
        'TOTAL_ASSETS_ALL_TYPES'                                    AS device_type,
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
                (SELECT count(*) FROM linx_assets_dedup)
            ) = 0 THEN 0
            ELSE round(
                100.0 * abs(
                    (SELECT count(DISTINCT device_name_norm) FROM foreseer_devices_dedup)
                    - (SELECT count(*) FROM linx_assets_dedup)
                ) / greatest(
                    (SELECT count(DISTINCT device_name_norm) FROM foreseer_devices_dedup),
                    (SELECT count(*) FROM linx_assets_dedup)
                ), 1
            )
        END AS pct_difference,

        (SELECT coalesce(sum(foreseer_ip_only_count), 0) FROM foreseer_ips_not_in_linx) AS foreseer_ips_not_in_linx_count,
        (SELECT coalesce(sum(linx_ip_only_count), 0)     FROM linx_ips_not_in_foreseer) AS linx_ips_not_in_foreseer_count
)

SELECT *
FROM (
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
        CASE WHEN foreseer_ips_not_in_linx_count + linx_ips_not_in_foreseer_count > 0 THEN 1 ELSE 0 END AS ip_mismatch_flag,
        NULL AS match_status, NULL AS match_score, NULL AS notes,
        NULL AS foreseer_asset_ip_addresses, NULL AS foreseer_assets_with_comms_ip,
        NULL AS linx_asset_ids, NULL AS linx_serial_numbers, NULL AS linx_asset_ip_addresses,
        NULL AS linx_assets_missing_serial, NULL AS linx_assets_missing_ip,
        NULL AS foreseer_ips_not_in_linx, NULL AS linx_ips_not_in_foreseer
    FROM totals
) AS final_results

ORDER BY
    CASE WHEN device_type = 'TOTAL_ASSETS_ALL_TYPES' THEN 1 ELSE 0 END,
    abs(count_difference) DESC,
    device_type;
