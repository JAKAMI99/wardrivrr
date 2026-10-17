from __future__ import annotations

import math
from typing import Iterable, Sequence

try:
    from db import connect
except ModuleNotFoundError as exc:
    if exc.name not in {"db", "backend", "backend.db"}:
        raise
    from backend.db import connect

PRECISION_PRESETS = {
    # Geocode is deferred (background job) so map points / navigation stay fast.
    "fast": {
        "max_samples_per_network": 40,
        "min_weight_floor_dbm": -100,
        "geocode": False,
    },
    "balanced": {
        "max_samples_per_network": 200,
        "min_weight_floor_dbm": -110,
        "geocode": False,
    },
    "precise": {
        "max_samples_per_network": 2000,
        "min_weight_floor_dbm": -120,
        "geocode": False,
    },
}

# Typical GPS fix when accuracy is missing from the capture file
DEFAULT_GPS_ACCURACY_M = 15.0
# Soft floor so a 1 m claim does not dominate absurdly
MIN_GPS_ACCURACY_M = 1.0


def rssi_weight(signal: float | None, floor_dbm: float = -110.0) -> float:
    if signal is None:
        return 1.0
    dbm = max(floor_dbm, min(-20.0, float(signal)))
    return 10.0 ** (dbm / 10.0)


def gps_accuracy_weight(accuracy_m: float | None) -> float:
    """
    Higher weight for tighter GPS fixes.
    accuracy_m is horizontal uncertainty in meters (WiGLE AccuracyMeters).
    Missing accuracy → neutral default (neither boost nor harsh penalty).
    """
    if accuracy_m is None or not math.isfinite(float(accuracy_m)) or float(accuracy_m) <= 0:
        acc = DEFAULT_GPS_ACCURACY_M
    else:
        acc = max(MIN_GPS_ACCURACY_M, float(accuracy_m))
    # 5 m ≈ strong, 50 m ≈ weak
    return 1.0 / (1.0 + (acc / 10.0) ** 2)


def sample_weight(
    signal: float | None,
    accuracy_m: float | None,
    floor_dbm: float,
) -> float:
    return rssi_weight(signal, floor_dbm) * gps_accuracy_weight(accuracy_m)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _fetch_samples(cur, network_ids: Sequence[str] | None, user_id: int | None, precision: str):
    preset = PRECISION_PRESETS.get(precision, PRECISION_PRESETS["balanced"])
    limit = preset["max_samples_per_network"]
    # Prefer strongest signals; include GPS accuracy for weighting
    cols = """
        network_id, name, encryption, network_type, channel,
        signal, altitude, lat, lon, seen_at, accuracy, user_id
    """
    if network_ids is None:
        if user_id is None:
            cur.execute(
                f"""
                SELECT {cols}
                FROM (
                    SELECT *,
                           row_number() OVER (
                             PARTITION BY COALESCE(user_id, 0), network_id
                             ORDER BY signal DESC NULLS LAST, seen_at DESC NULLS LAST
                           ) AS rn
                    FROM signal_samples
                    WHERE user_id IS NOT NULL
                ) t
                WHERE rn <= %s
                ORDER BY user_id, network_id
                """,
                (limit,),
            )
        else:
            cur.execute(
                f"""
                SELECT {cols}
                FROM (
                    SELECT *,
                           row_number() OVER (
                             PARTITION BY network_id
                             ORDER BY signal DESC NULLS LAST, seen_at DESC NULLS LAST
                           ) AS rn
                    FROM signal_samples
                    WHERE user_id = %s
                ) t
                WHERE rn <= %s
                ORDER BY network_id
                """,
                (user_id, limit),
            )
    elif not network_ids:
        return []
    else:
        cur.execute(
            f"""
            SELECT {cols}
            FROM (
                SELECT *,
                       row_number() OVER (
                         PARTITION BY network_id
                         ORDER BY signal DESC NULLS LAST, seen_at DESC NULLS LAST
                       ) AS rn
                FROM signal_samples
                WHERE user_id = %s AND network_id = ANY(%s)
            ) t
            WHERE rn <= %s
            ORDER BY network_id
            """,
            (user_id, list(network_ids), limit),
        )
    return cur.fetchall()


def _aggregate(rows: list, mode: str, precision: str, user_id: int | None) -> dict | None:
    if not rows:
        return None
    floor = PRECISION_PRESETS.get(precision, PRECISION_PRESETS["balanced"])["min_weight_floor_dbm"]

    sum_w = 0.0
    sum_lat = 0.0
    sum_lon = 0.0
    sum_alt_w = 0.0
    sum_alt = 0.0
    sum_sig_w = 0.0
    sum_sig = 0.0
    sum_gps_acc_w = 0.0
    sum_gps_acc = 0.0
    first_seen = None
    last_seen = None
    name = None
    encryption = None
    network_type = "WIFI"
    channel = None
    latest_ts = None
    weighted_points: list[tuple[float, float, float, float]] = []  # lat, lon, w, gps_acc

    sample_user_id = user_id
    for row in rows:
        # 0 nid, 1 name, 2 enc, 3 type, 4 ch, 5 signal, 6 alt, 7 lat, 8 lon, 9 seen, 10 accuracy, 11 user_id?
        sig = row[5]
        gps_acc = row[10] if len(row) > 10 else None
        if sample_user_id is None and len(row) > 11 and row[11] is not None:
            sample_user_id = int(row[11])
        w = sample_weight(sig, gps_acc, floor)
        lat = float(row[7])
        lon = float(row[8])
        sum_w += w
        sum_lat += lat * w
        sum_lon += lon * w
        acc_m = (
            float(gps_acc)
            if gps_acc is not None and math.isfinite(float(gps_acc)) and float(gps_acc) > 0
            else DEFAULT_GPS_ACCURACY_M
        )
        weighted_points.append((lat, lon, w, acc_m))

        alt = row[6]
        if alt is not None:
            sum_alt_w += w
            sum_alt += float(alt) * w

        if sig is not None:
            sum_sig_w += w
            sum_sig += float(sig) * w

        sum_gps_acc_w += w
        sum_gps_acc += acc_m * w

        seen = row[9]
        if seen is not None:
            if first_seen is None or seen < first_seen:
                first_seen = seen
            if last_seen is None or seen > last_seen:
                last_seen = seen
            if latest_ts is None or seen >= latest_ts:
                latest_ts = seen
                try:
                    from wigle import sanitize_network_name

                    name = sanitize_network_name(row[1], row[0])
                except Exception:
                    name = row[1]
                encryption = row[2]
                network_type = row[3] or "WIFI"
                channel = row[4]
        elif name is None:
            try:
                from wigle import sanitize_network_name

                name = sanitize_network_name(row[1], row[0])
            except Exception:
                name = row[1]
            encryption = row[2]
            network_type = row[3] or "WIFI"
            channel = row[4]

    if sum_w <= 0:
        return None

    lat = sum_lat / sum_w
    lon = sum_lon / sum_w
    altitude = (sum_alt / sum_alt_w) if sum_alt_w > 0 else None

    # Combined location uncertainty (meters):
    # sqrt( Σ w_i * (d_i² + gps_acc_i²) / Σ w_i )
    var_acc = 0.0
    for plat, plon, w, acc_m in weighted_points:
        d = haversine_m(lat, lon, plat, plon)
        var_acc += w * (d * d + acc_m * acc_m)
    location_accuracy_m = math.sqrt(var_acc / sum_w) if sum_w > 0 else None

    return {
        "user_id": sample_user_id,
        "network_id": rows[0][0],
        "name": name,
        "encryption": encryption,
        "network_type": network_type,
        "channel": channel,
        "sample_count": len(rows),
        "lat": lat,
        "lon": lon,
        "altitude": altitude,
        "avg_signal": (sum_sig / sum_sig_w) if sum_sig_w > 0 else None,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "localization_mode": mode,
        "location_accuracy_m": location_accuracy_m,
        "avg_gps_accuracy_m": (sum_gps_acc / sum_gps_acc_w) if sum_gps_acc_w > 0 else None,
        "address": None,
        "city": None,
        "postcode": None,
        "country": None,
        "country_code": None,
    }


def _attach_address(agg: dict) -> None:
    try:
        from geocode import reverse_geocode_cached
    except ModuleNotFoundError:
        from backend.geocode import reverse_geocode_cached

    geo = reverse_geocode_cached(float(agg["lat"]), float(agg["lon"]))
    if not geo:
        return
    agg["address"] = geo.get("display_name")
    addr = geo.get("address") or {}
    agg["city"] = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality")
    agg["postcode"] = addr.get("postcode")
    agg["country"] = addr.get("country")
    agg["country_code"] = addr.get("country_code")


UPSERT_SQL = """
INSERT INTO networks (
    user_id, network_id, name, encryption, network_type, channel, sample_count,
    lat, lon, altitude, avg_signal, first_seen, last_seen, localization_mode,
    address, city, postcode, country, country_code,
    location_accuracy_m, avg_gps_accuracy_m, computed_at
) VALUES (
    %(user_id)s, %(network_id)s, %(name)s, %(encryption)s, %(network_type)s, %(channel)s, %(sample_count)s,
    %(lat)s, %(lon)s, %(altitude)s, %(avg_signal)s, %(first_seen)s, %(last_seen)s,
    %(localization_mode)s,
    %(address)s, %(city)s, %(postcode)s, %(country)s, %(country_code)s,
    %(location_accuracy_m)s, %(avg_gps_accuracy_m)s, NOW()
)
ON CONFLICT (user_id, network_id) DO UPDATE SET
    name = COALESCE(EXCLUDED.name, networks.name),
    encryption = EXCLUDED.encryption,
    network_type = EXCLUDED.network_type,
    channel = EXCLUDED.channel,
    sample_count = EXCLUDED.sample_count,
    lat = EXCLUDED.lat,
    lon = EXCLUDED.lon,
    altitude = EXCLUDED.altitude,
    avg_signal = EXCLUDED.avg_signal,
    first_seen = LEAST(
        COALESCE(networks.first_seen, EXCLUDED.first_seen),
        EXCLUDED.first_seen
    ),
    last_seen = GREATEST(
        COALESCE(networks.last_seen, EXCLUDED.last_seen),
        EXCLUDED.last_seen
    ),
    localization_mode = EXCLUDED.localization_mode,
    address = EXCLUDED.address,
    city = EXCLUDED.city,
    postcode = EXCLUDED.postcode,
    country = EXCLUDED.country,
    country_code = EXCLUDED.country_code,
    location_accuracy_m = EXCLUDED.location_accuracy_m,
    avg_gps_accuracy_m = EXCLUDED.avg_gps_accuracy_m,
    computed_at = NOW()
"""


def recompute_networks(
    network_ids: Iterable[str] | None = None,
    mode: str = "2d",
    conn=None,
    user_id: int | None = None,
    precision: str = "balanced",
    geocode: bool | None = None,
) -> int:
    if mode not in {"2d", "3d"}:
        raise ValueError("mode must be '2d' or '3d'")
    if precision not in PRECISION_PRESETS:
        precision = "balanced"
    do_geocode = (
        PRECISION_PRESETS[precision]["geocode"] if geocode is None else bool(geocode)
    )

    ids = list(network_ids) if network_ids is not None else None
    own = conn is None
    if own:
        conn = connect()
    updated = 0
    try:
        with conn.cursor() as cur:
            rows = _fetch_samples(cur, ids, user_id, precision)
            by_id: dict[tuple, list] = {}
            for row in rows:
                uid = user_id if user_id is not None else (row[11] if len(row) > 11 else None)
                by_id.setdefault((uid, row[0]), []).append(row)
            for (uid, _nid), samples in by_id.items():
                agg = _aggregate(samples, mode, precision, uid)
                if not agg:
                    continue
                if not math.isfinite(agg["lat"]) or not math.isfinite(agg["lon"]):
                    continue
                if agg["user_id"] is None:
                    continue
                if do_geocode:
                    try:
                        _attach_address(agg)
                    except Exception:
                        pass
                cur.execute(UPSERT_SQL, agg)
                updated += 1
                if updated % 200 == 0:
                    conn.commit()
                    print(f"[localize] updated {updated}…", flush=True)
        conn.commit()
        if do_geocode:
            try:
                from geocode import flush_geocode_cache
            except ModuleNotFoundError:
                from backend.geocode import flush_geocode_cache
            flush_geocode_cache()
        return updated
    finally:
        if own:
            conn.close()


def recompute_2d(
    network_ids: Iterable[str] | None = None,
    conn=None,
    user_id: int | None = None,
    precision: str = "balanced",
    geocode: bool | None = None,
) -> int:
    return recompute_networks(
        network_ids,
        mode="2d",
        conn=conn,
        user_id=user_id,
        precision=precision,
        geocode=geocode,
    )


def recompute_3d(
    network_ids: Iterable[str] | None = None,
    conn=None,
    user_id: int | None = None,
    precision: str = "precise",
    geocode: bool | None = None,
) -> int:
    return recompute_networks(
        network_ids,
        mode="3d",
        conn=conn,
        user_id=user_id,
        precision=precision,
        geocode=geocode,
    )
