"""
Snap noisy GPS onto driveable road_segments (fog unlock geometry).

Default threshold: GPS_SNAP_THRESHOLD_M=8 (alias SNAP_TO_ROAD_M), hard-capped at 10.
Good GNSS only needs a few meters of rail/jitter forgiveness — never widen past 10.

Within threshold → ST_ClosestPoint on a nearby edge (heading-biased).
Beyond threshold → hold last good snap if still near (degraded), else raw GPS.
Never yank across the map to a distant road.

Unlock / fog MUST use snapped lat/lon from snap_to_road().
"""

from __future__ import annotations

import math
import os
import threading
import time
from typing import Any

from db import connect_dict

_SNAP_HARD_MAX_M = 10.0
_SNAP_DEFAULT_M = 8.0

GPS_SNAP_THRESHOLD_M = float(
    os.getenv("GPS_SNAP_THRESHOLD_M") or os.getenv("SNAP_TO_ROAD_M") or str(_SNAP_DEFAULT_M)
)
GPS_SNAP_ENABLED = (
    os.getenv("GPS_SNAP_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
)
_HEADING_PREF_DEG = float(os.getenv("GPS_SNAP_HEADING_PREF_DEG", "55"))
_CANDIDATE_LIMIT = 12
_HOLD_MAX_S = max(0.0, min(float(os.getenv("GPS_SNAP_HOLD_MAX_S", "6")), 8.0))

_lock = threading.Lock()
_last_good: dict[int, dict[str, Any]] = {}


def snap_threshold_m() -> float:
    # Floor 1 m, hard ceiling 10 m (rail / jitter only — do not widen).
    return max(1.0, min(float(GPS_SNAP_THRESHOLD_M), _SNAP_HARD_MAX_M))


def resolve_level_id(user_id: int) -> int | None:
    try:
        from db import get_user_setting

        raw = get_user_setting(user_id, "active_level_id", None)
        if raw and str(raw).isdigit():
            return int(raw)
    except Exception:
        pass
    return None


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _angle_diff(a: float, b: float) -> float:
    d = abs((a - b) % 360.0)
    return d if d <= 180.0 else 360.0 - d


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float | None:
    if abs(lat1 - lat2) < 1e-9 and abs(lon1 - lon2) < 1e-9:
        return None
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dλ = math.radians(lon2 - lon1)
    y = math.sin(dλ) * math.cos(φ2)
    x = math.cos(φ1) * math.sin(φ2) - math.sin(φ1) * math.cos(φ2) * math.cos(dλ)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _query_candidates(
    level_id: int,
    lat: float,
    lon: float,
    threshold_m: float,
) -> list[dict[str, Any]]:
    pad = max(0.00045, (threshold_m + 25.0) / 100_000.0)
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    WITH pt AS (
                      SELECT ST_SetSRID(ST_MakePoint(%s, %s), 4326) AS g
                    ),
                    cand AS (
                      SELECT
                        rs.id,
                        ST_Distance(rs.geom::geography, pt.g::geography) AS dist_m,
                        ST_ClosestPoint(rs.geom, pt.g) AS cp,
                        rs.geom AS geom
                      FROM road_segments rs
                      JOIN levels lv ON lv.id = rs.level_id
                      CROSS JOIN pt
                      WHERE rs.level_id = %s
                        AND (
                          lv.profile <> 'car'
                          OR rs.highway IN (
                            'motorway', 'motorway_link', 'trunk', 'trunk_link',
                            'primary', 'primary_link', 'secondary', 'secondary_link',
                            'tertiary', 'tertiary_link', 'unclassified',
                            'residential', 'living_street', 'service'
                          )
                        )
                        AND rs.geom && ST_Expand(pt.g, %s)
                        AND ST_DWithin(rs.geom::geography, pt.g::geography, %s)
                      ORDER BY dist_m ASC
                      LIMIT %s
                    )
                    SELECT
                      id,
                      dist_m,
                      ST_Y(cp) AS lat,
                      ST_X(cp) AS lon,
                      ST_Y(ST_LineInterpolatePoint(
                        ST_LineMerge(geom)::geometry,
                        GREATEST(0.0, LEAST(1.0,
                          ST_LineLocatePoint(ST_LineMerge(geom)::geometry, cp) - 0.01
                        ))
                      )) AS lat_a,
                      ST_X(ST_LineInterpolatePoint(
                        ST_LineMerge(geom)::geometry,
                        GREATEST(0.0, LEAST(1.0,
                          ST_LineLocatePoint(ST_LineMerge(geom)::geometry, cp) - 0.01
                        ))
                      )) AS lon_a,
                      ST_Y(ST_LineInterpolatePoint(
                        ST_LineMerge(geom)::geometry,
                        GREATEST(0.0, LEAST(1.0,
                          ST_LineLocatePoint(ST_LineMerge(geom)::geometry, cp) + 0.01
                        ))
                      )) AS lat_b,
                      ST_X(ST_LineInterpolatePoint(
                        ST_LineMerge(geom)::geometry,
                        GREATEST(0.0, LEAST(1.0,
                          ST_LineLocatePoint(ST_LineMerge(geom)::geometry, cp) + 0.01
                        ))
                      )) AS lon_b
                    FROM cand
                    """,
                    (lon, lat, level_id, pad, threshold_m, _CANDIDATE_LIMIT),
                )
                return list(cur.fetchall() or [])
            except Exception:
                conn.rollback()
                cur.execute(
                    """
                    WITH pt AS (
                      SELECT ST_SetSRID(ST_MakePoint(%s, %s), 4326) AS g
                    )
                    SELECT
                      rs.id,
                      ST_Distance(rs.geom::geography, pt.g::geography) AS dist_m,
                      ST_Y(ST_ClosestPoint(rs.geom, pt.g)) AS lat,
                      ST_X(ST_ClosestPoint(rs.geom, pt.g)) AS lon,
                      NULL::float AS lat_a,
                      NULL::float AS lon_a,
                      NULL::float AS lat_b,
                      NULL::float AS lon_b
                    FROM road_segments rs
                    JOIN levels lv ON lv.id = rs.level_id
                    CROSS JOIN pt
                    WHERE rs.level_id = %s
                      AND (
                        lv.profile <> 'car'
                        OR rs.highway IN (
                          'motorway', 'motorway_link', 'trunk', 'trunk_link',
                          'primary', 'primary_link', 'secondary', 'secondary_link',
                          'tertiary', 'tertiary_link', 'unclassified',
                          'residential', 'living_street', 'service'
                        )
                      )
                      AND rs.geom && ST_Expand(pt.g, %s)
                      AND ST_DWithin(rs.geom::geography, pt.g::geography, %s)
                    ORDER BY dist_m ASC
                    LIMIT %s
                    """,
                    (lon, lat, level_id, pad, threshold_m, _CANDIDATE_LIMIT),
                )
                return list(cur.fetchall() or [])
    except Exception:
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _pick_candidate(
    rows: list[dict[str, Any]],
    heading_deg: float | None,
) -> dict[str, Any] | None:
    if not rows:
        return None
    if heading_deg is None:
        return rows[0]

    best = None
    best_score = None
    for row in rows:
        dist = float(row.get("dist_m") or 0)
        heading_pen = 0.0
        if row.get("lat_a") is not None and row.get("lat_b") is not None:
            edge_brg = _bearing_deg(
                float(row["lat_a"]),
                float(row["lon_a"]),
                float(row["lat_b"]),
                float(row["lon_b"]),
            )
            if edge_brg is not None:
                d = min(
                    _angle_diff(heading_deg, edge_brg),
                    _angle_diff(heading_deg, (edge_brg + 180) % 360),
                )
                if d > _HEADING_PREF_DEG:
                    heading_pen = (d - _HEADING_PREF_DEG) * 0.75
        score = dist + heading_pen
        if best_score is None or score < best_score:
            best_score = score
            best = row
    return best or rows[0]


def snap_to_road(
    lon: float | None = None,
    lat: float | None = None,
    level_id: int | None = None,
    *,
    user_id: int | None = None,
    heading_deg: float | None = None,
    threshold_m: float | None = None,
) -> dict[str, Any]:
    """
    Snap (lon, lat) onto level road geometry.

    Positional form (legacy callers): snap_to_road(lon, lat, level_id)
    Keyword form preferred when user_id/heading available.
    """
    if lat is None or lon is None:
        raise TypeError("lat and lon are required")
    requested_thr = float(
        threshold_m if threshold_m is not None else snap_threshold_m()
    )
    # Keep the hard ceiling even for direct callers passing threshold_m.
    thr = max(1.0, min(requested_thr, _SNAP_HARD_MAX_M))
    uid = int(user_id) if user_id is not None else 0
    out: dict[str, Any] = {
        "lat": float(lat),
        "lon": float(lon),
        "raw_lat": float(lat),
        "raw_lon": float(lon),
        "snapped": False,
        "held": False,
        "degraded": False,
        "distance_m": None,
        "dist_m": None,  # alias for older callers
        "threshold_m": thr,
        "segment_id": None,
        "enabled": GPS_SNAP_ENABLED,
    }
    if not GPS_SNAP_ENABLED or level_id is None:
        return out

    rows = _query_candidates(int(level_id), float(lat), float(lon), thr)
    pick = _pick_candidate(rows, heading_deg)

    if pick and pick.get("lat") is not None and pick.get("lon") is not None:
        dist = float(pick.get("dist_m") or 0)
        out.update(
            {
                "lat": float(pick["lat"]),
                "lon": float(pick["lon"]),
                "snapped": True,
                "held": False,
                "degraded": False,
                "distance_m": dist,
                "dist_m": dist,
                "segment_id": pick.get("id"),
            }
        )
        if uid:
            with _lock:
                _last_good[uid] = {
                    "lat": out["lat"],
                    "lon": out["lon"],
                    "level_id": int(level_id),
                    "segment_id": out["segment_id"],
                    "saved_at": time.monotonic(),
                }
        return out

    if uid:
        with _lock:
            prev = _last_good.get(uid)
        if prev and prev.get("level_id") == int(level_id):
            hold_age = time.monotonic() - float(prev.get("saved_at") or 0)
            hold_dist = _haversine_m(
                float(lat), float(lon), float(prev["lat"]), float(prev["lon"])
            )
            if hold_age <= _HOLD_MAX_S and hold_dist <= thr * 3.0:
                out.update(
                    {
                        "lat": float(prev["lat"]),
                        "lon": float(prev["lon"]),
                        "snapped": False,
                        "held": True,
                        "degraded": True,
                        "distance_m": hold_dist,
                        "dist_m": hold_dist,
                        "segment_id": prev.get("segment_id"),
                        "hold_age_s": round(hold_age, 3),
                    }
                )
                return out
            if hold_age > _HOLD_MAX_S:
                with _lock:
                    if _last_good.get(uid) is prev:
                        _last_good.pop(uid, None)

    out["degraded"] = True
    return out


def clear_last_good(user_id: int) -> None:
    with _lock:
        _last_good.pop(user_id, None)
