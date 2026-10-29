from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any

from db import connect_dict
from geocode import normalize_mac, resolve_search_area, reverse_geocode


def _iso(v):
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def _vendor(row: dict) -> str | None:
    v = row.get("vendor")
    if isinstance(v, str) and v.strip():
        return v.strip()
    # Until backfill finishes (or OUI unknown), resolve from the local IEEE DB
    try:
        from oui import lookup_vendor

        return lookup_vendor(row.get("network_id"))
    except Exception:
        return None


def row_to_result(row: dict, *, reverse: bool = False) -> dict:
    out = {
        "netid": row["network_id"],
        "ssid": row.get("name"),
        "name": row.get("name"),
        "encryption": row.get("encryption"),
        "type": row.get("network_type"),
        "channel": row.get("channel"),
        "sample_count": row.get("sample_count"),
        "latitude": row.get("lat"),
        "longitude": row.get("lon"),
        "altitude": row.get("altitude"),
        "signal": row.get("avg_signal"),
        "avg_signal": row.get("avg_signal"),
        "firstseen": _iso(row.get("first_seen")),
        "lastseen": _iso(row.get("last_seen")),
        "localization_mode": row.get("localization_mode"),
        "computed_at": _iso(row.get("computed_at")),
        "address": row.get("address"),
        "city": row.get("city"),
        "postcode": row.get("postcode"),
        "country": row.get("country"),
        "country_code": row.get("country_code"),
        "location_accuracy_m": row.get("location_accuracy_m"),
        "avg_gps_accuracy_m": row.get("avg_gps_accuracy_m"),
        "vendor": _vendor(row),
        "place": row.get("address"),
    }
    # Live reverse only if DB has no address yet and caller asked for reverse
    if (
        reverse
        and not out.get("address")
        and row.get("lat") is not None
        and row.get("lon") is not None
    ):
        try:
            geo = reverse_geocode(float(row["lat"]), float(row["lon"]))
            if geo:
                out["place"] = geo.get("display_name")
                out["address"] = geo.get("display_name")
                addr = geo.get("address") or {}
                out["city"] = addr.get("city") or addr.get("town") or addr.get("village")
                out["postcode"] = addr.get("postcode")
                out["country"] = addr.get("country")
                out["country_code"] = addr.get("country_code")
        except Exception:
            pass
    return out


def encode_cursor(last_seen, network_id: str) -> str:
    payload = {"ls": _iso(last_seen), "id": network_id}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def decode_cursor(token: str | None) -> dict | None:
    if not token:
        return None
    try:
        return json.loads(base64.urlsafe_b64decode(token.encode()).decode())
    except Exception:
        return None


def _where(
    user_id: int,
    *,
    ssid: str | None,
    ssid_exact: bool,
    netid: str | None,
    mac: str | None,
    network_type: str | None,
    encryption: str | None,
    vendor: str | None,
    exclude_no_ssid: bool,
    seen_after: datetime | None,
    seen_before: datetime | None,
    min_samples: int | None,
    localization_mode: str | None,
    bbox: tuple[float, float, float, float] | None,
    city: str | None,
    postcode_stored: str | None,
    address_q: str | None,
    max_location_accuracy_m: float | None,
    near_lat: float | None,
    near_lon: float | None,
    radius_m: float | None,
    cursor: dict | None,
) -> tuple[str, list[Any]]:
    sql = " WHERE user_id = %s"
    params: list[Any] = [user_id]

    mac_src = normalize_mac(mac or netid)
    if mac_src:
        sql += " AND translate(upper(network_id), ':.- ', '') LIKE %s"
        params.append(mac_src + "%")

    if ssid:
        if ssid_exact:
            sql += " AND name = %s"
            params.append(ssid)
        else:
            sql += " AND name ILIKE %s"
            params.append(f"%{ssid}%")

    if vendor:
        try:
            from oui import vendor_match_clause

            clause, vparams = vendor_match_clause(vendor)
            sql += f" AND {clause}"
            params.extend(vparams)
        except Exception:
            sql += " AND vendor = %s"
            params.append(vendor.strip())

    if exclude_no_ssid:
        sql += """
            AND NOT (
                name IS NULL OR btrim(name) = ''
                OR lower(btrim(name)) IN ('(no ssid)', '<no ssid>', '[no ssid]', 'null', 'none')
            )
        """

    if network_type:
        sql += " AND upper(network_type) = %s"
        params.append(network_type.upper())

    if encryption:
        if encryption.lower() in ("none", "open"):
            sql += " AND (encryption IN ('None', 'Unknown', 'Open') OR encryption IS NULL)"
        else:
            sql += " AND encryption ILIKE %s"
            params.append(f"%{encryption}%")

    if seen_after:
        sql += " AND last_seen >= %s"
        params.append(seen_after)
    if seen_before:
        sql += " AND last_seen <= %s"
        params.append(seen_before)

    if min_samples is not None:
        sql += " AND sample_count >= %s"
        params.append(min_samples)

    if localization_mode:
        sql += " AND localization_mode = %s"
        params.append(localization_mode)

    if city:
        sql += " AND city ILIKE %s"
        params.append(f"%{city}%")

    if address_q:
        sql += " AND address ILIKE %s"
        params.append(f"%{address_q}%")

    if max_location_accuracy_m is not None:
        sql += " AND location_accuracy_m IS NOT NULL AND location_accuracy_m <= %s"
        params.append(max_location_accuracy_m)

    if bbox:
        west, south, east, north = bbox
        # Prefer stored postcode matches + anything still only in the geocoded envelope
        if postcode_stored:
            sql += """
                AND (
                    postcode = %s
                    OR geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)
                )
            """
            params.extend([postcode_stored, west, south, east, north])
        else:
            sql += " AND geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)"
            params.extend([west, south, east, north])
    elif postcode_stored:
        sql += " AND postcode = %s"
        params.append(postcode_stored)

    if near_lat is not None and near_lon is not None and radius_m:
        sql += """
            AND ST_DWithin(
                geom::geography,
                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                %s
            )
        """
        params.extend([near_lon, near_lat, radius_m])

    if cursor:
        ls = cursor.get("ls")
        nid = cursor.get("id")
        if ls and nid:
            sql += """
                AND (
                    last_seen < %s::timestamptz
                    OR (last_seen = %s::timestamptz AND network_id > %s)
                    OR (last_seen IS NULL AND %s::timestamptz IS NOT NULL)
                )
            """
            params.extend([ls, ls, nid, ls])

    return sql, params


def search_networks(
    user_id: int,
    *,
    ssid: str | None = None,
    ssid_exact: bool = False,
    netid: str | None = None,
    mac: str | None = None,
    network_type: str | None = None,
    encryption: str | None = None,
    vendor: str | None = None,
    exclude_no_ssid: bool = False,
    seen_after: datetime | None = None,
    seen_before: datetime | None = None,
    min_samples: int | None = None,
    localization_mode: str | None = None,
    place: str | None = None,
    postalcode: str | None = None,
    zip_code: str | None = None,
    country: str | None = None,
    city: str | None = None,
    address_q: str | None = None,
    max_location_accuracy_m: float | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    latrange1: float | None = None,
    latrange2: float | None = None,
    longrange1: float | None = None,
    longrange2: float | None = None,
    near: str | None = None,
    radius_m: float = 500.0,
    search_after: str | None = None,
    limit: int = 100,
    reverse: bool = False,
    onlyresults: bool = False,
) -> dict:
    pc = (postalcode or zip_code or "").strip() or None
    area = resolve_search_area(
        place=place,
        postalcode=postalcode,
        zip_code=zip_code,
        country=country,
        bbox=bbox,
        latrange1=latrange1,
        latrange2=latrange2,
        longrange1=longrange1,
        longrange2=longrange2,
    )
    if area.get("error"):
        # Still allow filtering by stored postcode/city once addresses exist
        if not (pc or city or address_q):
            return {
                "success": False,
                "results": [],
                "totalResults": 0,
                "resultCount": 0,
                "searchAfter": None,
                "error": area["error"],
                "geocode": None,
                "bbox": None,
            }
        area = {"bbox": None, "geocode": None, "candidates": []}

    resolved_bbox = area.get("bbox")
    near_lat = near_lon = None
    if near:
        parts = [p.strip() for p in near.split(",")]
        if len(parts) != 2:
            return {
                "success": False,
                "results": [],
                "totalResults": 0,
                "resultCount": 0,
                "error": "near must be lat,lon",
            }
        near_lat, near_lon = float(parts[0]), float(parts[1])

    cursor = decode_cursor(search_after)
    filter_kw = dict(
        ssid=ssid,
        ssid_exact=ssid_exact,
        netid=netid,
        mac=mac,
        network_type=network_type,
        encryption=encryption,
        vendor=(vendor or "").strip() or None,
        exclude_no_ssid=exclude_no_ssid,
        seen_after=seen_after,
        seen_before=seen_before,
        min_samples=min_samples,
        localization_mode=localization_mode,
        bbox=resolved_bbox,
        city=city,
        postcode_stored=pc,
        address_q=address_q,
        max_location_accuracy_m=max_location_accuracy_m,
        near_lat=near_lat,
        near_lon=near_lon,
        radius_m=radius_m if near_lat is not None else None,
        cursor=cursor,
    )
    where_sql, params = _where(user_id, **filter_kw)
    limit = max(1, min(int(limit), 1000))
    use_near = near_lat is not None and near_lon is not None

    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM networks" + where_sql, params)
            total = cur.fetchone()["n"]

            select_cols = """
                network_id, name, encryption, network_type, channel,
                sample_count, lat, lon, altitude, avg_signal,
                first_seen, last_seen, localization_mode, computed_at,
                address, city, postcode, country, country_code,
                location_accuracy_m, avg_gps_accuracy_m, vendor
            """
            if use_near:
                q = f"""
                    SELECT {select_cols},
                           ST_Distance(
                               geom::geography,
                               ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography
                           ) AS distance_m
                    FROM networks
                    {where_sql}
                    ORDER BY distance_m ASC NULLS LAST, network_id ASC
                    LIMIT %s
                """
                cur.execute(q, [near_lon, near_lat, *params, limit])
            else:
                q = f"""
                    SELECT {select_cols}
                    FROM networks
                    {where_sql}
                    ORDER BY last_seen DESC NULLS LAST, network_id ASC
                    LIMIT %s
                """
                cur.execute(q, [*params, limit])
            rows = cur.fetchall()
    finally:
        conn.close()

    results = []
    for row in rows:
        item = row_to_result(row, reverse=reverse)
        if row.get("distance_m") is not None:
            item["distance_m"] = round(float(row["distance_m"]), 1)
        results.append(item)

    next_cursor = None
    if len(rows) == limit:
        last = rows[-1]
        next_cursor = encode_cursor(last.get("last_seen"), last["network_id"])

    out: dict[str, Any] = {
        "success": True,
        "results": results,
        "totalResults": total,
        "resultCount": len(results),
        "searchAfter": next_cursor,
    }
    if not onlyresults:
        out["geocode"] = area.get("geocode")
        out["bbox"] = list(resolved_bbox) if resolved_bbox else None
        out["query"] = {
            "ssid": ssid,
            "mac": mac or netid,
            "vendor": vendor,
            "place": place,
            "postalcode": postalcode or zip_code,
            "type": network_type,
            "near": near,
            "radius_m": radius_m if near else None,
        }
    return out


def get_network_detail(
    user_id: int,
    netid: str,
    *,
    include_samples: bool = False,
    reverse: bool = True,
) -> dict | None:
    mac = normalize_mac(netid) or (netid or "").upper().replace(":", "").replace("-", "")
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT network_id, name, encryption, network_type, channel,
                       sample_count, lat, lon, altitude, avg_signal,
                       first_seen, last_seen, localization_mode, computed_at,
                       address, city, postcode, country, country_code,
                       location_accuracy_m, avg_gps_accuracy_m, vendor
                FROM networks
                WHERE user_id = %s
                  AND (
                    lower(network_id) = lower(%s)
                    OR translate(upper(network_id), ':.- ', '') = %s
                  )
                LIMIT 1
                """,
                (user_id, netid, mac),
            )
            row = cur.fetchone()
            if not row:
                return None
            detail = row_to_result(row, reverse=reverse)
            if include_samples:
                cur.execute(
                    """
                    SELECT COUNT(*) AS n,
                           MIN(signal) AS min_signal,
                           MAX(signal) AS max_signal,
                           AVG(signal) AS avg_signal,
                           MIN(seen_at) AS first_seen,
                           MAX(seen_at) AS last_seen,
                           ST_XMin(ST_Extent(geom)) AS west,
                           ST_YMin(ST_Extent(geom)) AS south,
                           ST_XMax(ST_Extent(geom)) AS east,
                           ST_YMax(ST_Extent(geom)) AS north
                    FROM signal_samples
                    WHERE user_id = %s AND network_id = %s
                    """,
                    (user_id, row["network_id"]),
                )
                samp = cur.fetchone()
                detail["samples"] = {
                    "count": samp["n"],
                    "min_signal": samp["min_signal"],
                    "max_signal": samp["max_signal"],
                    "avg_signal": (
                        float(samp["avg_signal"]) if samp["avg_signal"] is not None else None
                    ),
                    "first_seen": _iso(samp["first_seen"]),
                    "last_seen": _iso(samp["last_seen"]),
                    "bbox": (
                        [samp["west"], samp["south"], samp["east"], samp["north"]]
                        if samp["west"] is not None
                        else None
                    ),
                }
            return detail
    finally:
        conn.close()


def search_geojson(user_id: int, **kwargs) -> dict:
    kwargs.pop("reverse", None)
    data = search_networks(user_id, reverse=False, **kwargs)
    features = [
        {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [r["longitude"], r["latitude"]],
            },
            "properties": r,
        }
        for r in (data.get("results") or [])
        if r.get("longitude") is not None and r.get("latitude") is not None
    ]
    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "totalResults": data.get("totalResults"),
            "resultCount": data.get("resultCount"),
            "searchAfter": data.get("searchAfter"),
            "geocode": data.get("geocode"),
            "bbox": data.get("bbox"),
            "success": data.get("success", True),
            "error": data.get("error"),
        },
    }
