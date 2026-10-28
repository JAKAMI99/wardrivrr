from __future__ import annotations

import json
import math
import os
import time
import urllib.parse
import urllib.request
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from cpu_workers import map_build_workers
from db import connect, connect_dict
from drive_profiles import (
    COMPLETE_PCT,
    VALID_PROFILES,
    all_playable_highways,
    is_complete,
    is_parking_way,
    normalize_profile,
    profile_highways,
    profile_label,
    profile_uses_road_snap,
)
from geofabrik import download_pbf, resolve_feature, search_places
from paths import level_dir

# Workers for clip + segmentize (CPU-bound). Scales with cores; see cpu_workers.py.
_BUILD_WORKERS = map_build_workers()

# Back-compat export — prefer drive_profiles.profile_highways()
PROFILE_HIGHWAYS = {
    "foot": profile_highways("foot"),
    "bicycle": profile_highways("bicycle"),
    "car": profile_highways("small_car"),
    "small_car": profile_highways("small_car"),
    "big_car": profile_highways("big_car"),
}

SEGMENT_TARGET_M = 20.0


def _point_in_ring(lon: float, lat: float, ring: list) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = float(ring[i][0]), float(ring[i][1])
        xj, yj = float(ring[j][0]), float(ring[j][1])
        if ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / ((yj - yi) + 1e-15) + xi
        ):
            inside = not inside
        j = i
    return inside


def point_in_boundary(lon: float, lat: float, geom: dict | None) -> bool:
    """GeoJSON Polygon / MultiPolygon containment (lon, lat)."""
    if not geom:
        return True
    gtype = geom.get("type")
    coords = geom.get("coordinates") or []
    if gtype == "Polygon":
        if not coords:
            return False
        if not _point_in_ring(lon, lat, coords[0]):
            return False
        for hole in coords[1:]:
            if _point_in_ring(lon, lat, hole):
                return False
        return True
    if gtype == "MultiPolygon":
        return any(
            point_in_boundary(lon, lat, {"type": "Polygon", "coordinates": poly})
            for poly in coords
        )
    return True


def _geom_bbox(geom: dict | None) -> list[float] | None:
    if not geom:
        return None
    coords = geom.get("coordinates") or []
    flat: list[tuple[float, float]] = []

    def walk(c):
        if isinstance(c, (list, tuple)) and c and isinstance(c[0], (int, float)):
            flat.append((float(c[0]), float(c[1])))
        elif isinstance(c, (list, tuple)):
            for item in c:
                walk(item)

    walk(coords)
    if not flat:
        return None
    lons = [p[0] for p in flat]
    lats = [p[1] for p in flat]
    return [min(lons), min(lats), max(lons), max(lats)]


def _coords_in_bbox(coords: list[tuple[float, float]], bbox: list[float]) -> bool:
    minlon, minlat, maxlon, maxlat = bbox
    return any(minlon <= lon <= maxlon and minlat <= lat <= maxlat for lon, lat in coords)


def way_intersects_boundary(
    coords: list[tuple[float, float]],
    geom: dict | None,
    *,
    geom_bbox: list[float] | None = None,
) -> bool:
    if not geom:
        return True
    bb = geom_bbox or _geom_bbox(geom)
    if bb and not _coords_in_bbox(coords, bb):
        return False
    # Sample a few points first — enough for playable road inclusion
    n = len(coords)
    if n <= 4:
        sample = coords
    else:
        sample = [coords[0], coords[n // 3], coords[(2 * n) // 3], coords[-1]]
    return any(point_in_boundary(lon, lat, geom) for lon, lat in sample)


def _clip_ways_chunk(
    ways_chunk: list,
    boundary: dict,
    geom_bbox: list[float] | None,
) -> list:
    """Module-level for ProcessPoolExecutor pickling on Windows."""
    return [
        w
        for w in ways_chunk
        if way_intersects_boundary(w[3], boundary, geom_bbox=geom_bbox)
    ]


def _seg_inside_boundary(
    seg: list[tuple[float, float]], boundary: dict | None
) -> bool:
    """Keep a segment only if its midpoint (or any vertex) lies in the level polygon."""
    if not boundary:
        return True
    mid = seg[len(seg) // 2]
    if point_in_boundary(float(mid[0]), float(mid[1]), boundary):
        return True
    return any(point_in_boundary(float(lon), float(lat), boundary) for lon, lat in seg)


def _segmentize_ways_chunk(
    ways_chunk: list,
    level_id: int,
    boundary: dict | None = None,
) -> tuple[list[tuple], float]:
    """Build insert rows for a chunk of ways (CPU work; DB write stays single-threaded)."""
    batch: list[tuple] = []
    total_m = 0.0
    for osm_id, hw, name, coords in ways_chunk:
        for seg in segmentize_coords(coords):
            if not _seg_inside_boundary(seg, boundary):
                continue
            length = _line_length_m(seg)
            if length < 1:
                continue
            total_m += length
            wkt = "LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in seg) + ")"
            batch.append((level_id, osm_id, hw, name, wkt, length))
    return batch, total_m


def clip_road_segments_to_boundary(level_id: int) -> dict:
    """
    Drop road_segments whose midpoint falls outside the level polygon.
    Fixes legacy builds that kept whole OSM ways after a touch-test only.
    """
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM road_segments r
                USING levels l
                WHERE r.level_id = l.id
                  AND l.id = %s
                  AND l.bbox IS NOT NULL
                  AND NOT ST_Intersects(
                    ST_LineInterpolatePoint(r.geom, 0.5),
                    l.bbox
                  )
                """,
                (level_id,),
            )
            deleted = cur.rowcount
            cur.execute(
                """
                UPDATE levels SET
                  road_km = sub.km,
                  updated_at = NOW()
                FROM (
                  SELECT COALESCE(SUM(length_m), 0) / 1000.0 AS km
                  FROM road_segments
                  WHERE level_id = %s
                ) sub
                WHERE levels.id = %s
                RETURNING road_km
                """,
                (level_id, level_id),
            )
            row = cur.fetchone()
            _update_level_explored_stats(cur, level_id)
        conn.commit()
        return {
            "deleted": int(deleted or 0),
            "road_km": float(row[0] or 0) if row else None,
        }
    finally:
        conn.close()


def _chunked(items: list, n_chunks: int) -> list[list]:
    if not items:
        return []
    n_chunks = max(1, min(n_chunks, len(items)))
    size = math.ceil(len(items) / n_chunks)
    return [items[i : i + size] for i in range(0, len(items), size)]


def _executor(workers: int):
    """Process pool for multi-core; threads if processes can't start (e.g. frozen)."""
    try:
        return ProcessPoolExecutor(max_workers=workers)
    except Exception:
        return ThreadPoolExecutor(max_workers=workers)


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def segmentize_coords(coords: list[tuple[float, float]], target_m: float = SEGMENT_TARGET_M):
    """coords as (lon, lat). Yields list of (lon,lat) polylines ~target_m."""
    if len(coords) < 2:
        return
    current = [coords[0]]
    acc = 0.0
    for i in range(1, len(coords)):
        lon0, lat0 = current[-1]
        lon1, lat1 = coords[i]
        d = haversine_m(lat0, lon0, lat1, lon1)
        if d <= 0:
            continue
        if acc + d < target_m:
            current.append(coords[i])
            acc += d
            continue
        # split along edge
        remaining = target_m - acc
        while remaining <= d and d > 0:
            t = remaining / d
            lon = lon0 + (lon1 - lon0) * t
            lat = lat0 + (lat1 - lat0) * t
            current.append((lon, lat))
            yield list(current)
            current = [(lon, lat)]
            lon0, lat0 = lon, lat
            d = haversine_m(lat0, lon0, lat1, lon1)
            remaining = target_m
            acc = 0.0
        current.append(coords[i])
        acc = haversine_m(current[0][1], current[0][0], coords[i][1], coords[i][0]) if len(current) == 2 else haversine_m(lat0, lon0, lat1, lon1)
    if len(current) >= 2:
        yield current


def _line_length_m(coords: list[tuple[float, float]]) -> float:
    total = 0.0
    for i in range(1, len(coords)):
        lon0, lat0 = coords[i - 1]
        lon1, lat1 = coords[i]
        total += haversine_m(lat0, lon0, lat1, lon1)
    return total


def _extract_ways_osmium(
    pbf_path: Path,
    allowed: set[str],
    bbox: list[float] | None = None,
):
    """
    Read highway ways from a PBF. When bbox is set, skip ways that do not
    touch it — critical so we don't clip an entire regional extract in Python.
    """
    import osmium

    pad = 0.01
    bb = None
    if bbox and len(bbox) == 4:
        bb = [
            float(bbox[0]) - pad,
            float(bbox[1]) - pad,
            float(bbox[2]) + pad,
            float(bbox[3]) + pad,
        ]

    class Handler(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.ways: list[tuple[int, str, str | None, list[tuple[float, float]]]] = []

        def way(self, w):
            hw = w.tags.get("highway")
            if not hw or hw not in allowed:
                return
            # Drop parking lots / aisles entirely from the playable net
            tags = {k: w.tags.get(k) for k in ("highway", "service", "amenity") if w.tags.get(k)}
            if is_parking_way(tags):
                return
            if not w.is_closed() and len(w.nodes) < 2:
                return
            coords = []
            try:
                for n in w.nodes:
                    if not n.location.valid():
                        return
                    coords.append((n.location.lon, n.location.lat))
            except osmium.InvalidLocationError:
                return
            if len(coords) < 2:
                return
            if bb and not _coords_in_bbox(coords, bb):
                return
            self.ways.append((w.id, hw, w.tags.get("name"), coords))

    h = Handler()
    h.apply_file(str(pbf_path), locations=True)
    return h.ways


def _extract_ways_overpass(bbox: list[float], allowed: set[str]):
    """bbox: [minlon, minlat, maxlon, maxlat]. Fallback when osmium unavailable."""
    minlon, minlat, maxlon, maxlat = bbox
    hw_regex = "|".join(sorted(allowed))
    query = f"""
    [out:json][timeout:180];
    (
      way["highway"~"^({hw_regex})$"]({minlat},{minlon},{maxlat},{maxlon});
    );
    out geom;
    """
    url = "https://overpass-api.de/api/interpreter"
    data = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request(
        url, data=data, headers={"User-Agent": "wardrivrr/1.0"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=200) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    ways = []
    for el in payload.get("elements") or []:
        if el.get("type") != "way":
            continue
        geom = el.get("geometry") or []
        coords = [(g["lon"], g["lat"]) for g in geom]
        if len(coords) < 2:
            continue
        tags = el.get("tags") or {}
        hw = tags.get("highway")
        if hw not in allowed:
            continue
        if is_parking_way(tags):
            continue
        ways.append((el["id"], hw, tags.get("name"), coords))
    return ways


_LEVEL_SELECT = """
    SELECT id, name, place_query, geofabrik_id, geofabrik_name, profile,
           status, road_km, disk_bytes, networks_count, networks_wifi,
           networks_bt, networks_ble, explored_km, explored_pct,
           place_kind, geoname_id, parent_geoname_id, parent_label, part_label,
           osm_relation_id, osm_admin_level,
           error, created_at, updated_at, pbf_url,
           CASE WHEN bbox IS NOT NULL THEN
             ARRAY[ST_XMin(bbox), ST_YMin(bbox), ST_XMax(bbox), ST_YMax(bbox)]
           END AS bbox,
           CASE WHEN bbox IS NOT NULL THEN ST_AsGeoJSON(bbox)::json END AS boundary
"""


def count_levels_for_extract(user_id: int, geofabrik_id: str) -> int:
    """How many of this user's levels already use the same regional map pack."""
    if not geofabrik_id:
        return 0
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)::int AS n FROM levels
                WHERE user_id = %s AND geofabrik_id = %s AND status <> 'error'
                """,
                (user_id, geofabrik_id),
            )
            row = cur.fetchone()
            return int(row["n"] or 0) if row else 0
    finally:
        conn.close()


def _short_pack_name(
    geofabrik_id: str | None,
    geofabrik_name: str | None = None,
    resolved_name: str | None = None,
) -> str | None:
    """Friendly pack label, e.g. arnsberg-regbez → Arnsberg."""
    leaf = (geofabrik_id or "").strip().split("/")[-1]
    if leaf:
        for suffix in ("-regbez", "-kreis", "-stadt", "-bezirk"):
            if leaf.endswith(suffix):
                leaf = leaf[: -len(suffix)]
                break
        if leaf:
            return leaf.replace("-", " ").title()
    return geofabrik_name or resolved_name or None


def _enrich_levels_pack_meta(levels: list[dict]) -> list[dict]:
    """Attach pack display name, size, and how many sibling levels share the extract."""
    if not levels:
        return levels
    from collections import Counter

    counts: Counter[str] = Counter()
    for lv in levels:
        gid = lv.get("geofabrik_id")
        if gid and lv.get("status") != "error":
            counts[gid] += 1

    feat_cache: dict[str, dict] = {}
    for lv in levels:
        gid = lv.get("geofabrik_id") or ""
        if gid and gid not in feat_cache:
            feat = resolve_feature(gid)
            if feat:
                from geofabrik import feature_summary

                feat_cache[gid] = feature_summary(feat)
            else:
                feat_cache[gid] = {}
        summary = feat_cache.get(gid) or {}
        n = int(counts.get(gid, 0)) if gid else 0
        lv["pack_name"] = _short_pack_name(
            gid, lv.get("geofabrik_name"), summary.get("name")
        )
        lv["pack_size_bytes"] = summary.get("size_bytes") or lv.get("disk_bytes")
        lv["pack_levels_count"] = n
        lv["pack_other_levels"] = max(0, n - 1) if gid else 0
        lv["profile_norm"] = normalize_profile(lv.get("profile"))
        lv["profile_label"] = profile_label(lv.get("profile"))
        lv["complete"] = is_complete(lv.get("explored_pct"))
        lv["complete_pct"] = COMPLETE_PCT
    return levels


def find_duplicate_level(
    user_id: int,
    *,
    place_kind: str,
    osm_relation_id: int | None = None,
    geoname_id: int | None = None,
    place_query: str | None = None,
    geofabrik_id: str | None = None,
) -> dict | None:
    """Return an existing non-error level for the same city/district outline."""
    kind = (place_kind or "city").strip().lower()
    if kind == "city_part":
        kind = "district"
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            if osm_relation_id is not None:
                cur.execute(
                    _LEVEL_SELECT
                    + """
                    FROM levels
                    WHERE user_id = %s AND osm_relation_id = %s AND place_kind = %s
                      AND status <> 'error'
                    ORDER BY id DESC LIMIT 1
                    """,
                    (user_id, osm_relation_id, kind),
                )
                hit = cur.fetchone()
                if hit:
                    return hit
            if kind == "city" and geoname_id is not None:
                cur.execute(
                    _LEVEL_SELECT
                    + """
                    FROM levels
                    WHERE user_id = %s AND geoname_id = %s AND place_kind = 'city'
                      AND status <> 'error'
                    ORDER BY id DESC LIMIT 1
                    """,
                    (user_id, geoname_id),
                )
                hit = cur.fetchone()
                if hit:
                    return hit
            # Fallback: same pack + normalized place label (covers missing OSM / GeoNames ids)
            pq = (place_query or "").strip().lower()
            gid = (geofabrik_id or "").strip()
            if pq and gid:
                cur.execute(
                    _LEVEL_SELECT
                    + """
                    FROM levels
                    WHERE user_id = %s AND place_kind = %s
                      AND geofabrik_id = %s
                      AND lower(trim(place_query)) = %s
                      AND status <> 'error'
                    ORDER BY id DESC LIMIT 1
                    """,
                    (user_id, kind, gid, pq),
                )
                return cur.fetchone()
        return None
    finally:
        conn.close()


def create_level(
    user_id: int,
    name: str,
    place_query: str,
    profile: str | None,
    geofabrik_id: str,
    place_bbox: list[float] | None = None,
    place_boundary: dict | None = None,
    place_kind: str = "city",
    geoname_id: int | None = None,
    parent_geoname_id: int | None = None,
    parent_label: str | None = None,
    part_label: str | None = None,
    osm_relation_id: int | None = None,
    osm_admin_level: int | None = None,
) -> dict:
    # profile = last-used Navigate default only; map always imports full playable graph
    if profile and profile not in VALID_PROFILES:
        raise ValueError("profile must be big_car, small_car, bicycle, or foot")
    profile = normalize_profile(profile)
    kind = (place_kind or "city").strip().lower()
    if kind == "city_part":
        kind = "district"
    if kind not in {"city", "district"}:
        raise ValueError("place_kind must be city or district")
    # Fixed naming: "Köln" or "Köln, Innenstadt" — not user-editable
    from place_prepare import fixed_level_name

    if kind == "district":
        if ", " in (name or ""):
            city_bit, dist_bit = [p.strip() for p in name.split(",", 1)]
        else:
            city_bit = (parent_label or "").split(",")[0].strip() or "City"
            dist_bit = (name or "").strip()
        name = fixed_level_name(city_bit, dist_bit)
        parent_label = city_bit
    else:
        city_bit = (name or parent_label or "").split(",")[0].strip()
        name = fixed_level_name(city_bit)
        parent_label = name

    dup = find_duplicate_level(
        user_id,
        place_kind=kind,
        osm_relation_id=osm_relation_id,
        geoname_id=geoname_id,
        place_query=place_query,
        geofabrik_id=geofabrik_id,
    )
    if dup:
        raise ValueError(
            f"You already have a level for this area: {dup.get('name')} (#{dup.get('id')}). "
            "Switch vehicle mode in Navigate — do not create another level."
        )

    feat = resolve_feature(geofabrik_id)
    if not feat or not feat.get("pbf_url"):
        raise ValueError("Unknown map pack")
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO levels (
                    user_id, name, place_query, geofabrik_id, geofabrik_name,
                    pbf_url, profile, status,
                    place_kind, geoname_id, parent_geoname_id, parent_label,
                    part_label, osm_relation_id, osm_admin_level
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s,%s,%s,%s,%s,%s)
                RETURNING *
                """,
                (
                    user_id,
                    name,
                    place_query,
                    feat["id"],
                    feat["name"],
                    feat["pbf_url"],
                    profile,
                    kind,
                    geoname_id,
                    parent_geoname_id,
                    parent_label,
                    part_label,
                    osm_relation_id,
                    osm_admin_level,
                ),
            )
            level = cur.fetchone()
            # Exact city boundary when provided; else envelope fallback
            if place_boundary and place_boundary.get("type") in {"Polygon", "MultiPolygon"}:
                cur.execute(
                    """
                    UPDATE levels SET
                      bbox = ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326),
                      updated_at = NOW()
                    WHERE id = %s
                    """,
                    (json.dumps(place_boundary), level["id"]),
                )
            else:
                bb = place_bbox if place_bbox and len(place_bbox) == 4 else feat.get("bbox")
                if bb and len(bb) == 4:
                    minlon, minlat, maxlon, maxlat = [float(x) for x in bb]
                    cur.execute(
                        """
                        UPDATE levels SET bbox = ST_MakeEnvelope(%s,%s,%s,%s,4326)
                        WHERE id = %s
                        """,
                        (minlon, minlat, maxlon, maxlat, level["id"]),
                    )
            cur.execute(
                _LEVEL_SELECT + " FROM levels WHERE id = %s",
                (level["id"],),
            )
            level = cur.fetchone()
        conn.commit()
        return level
    finally:
        conn.close()


def list_levels(user_id: int) -> list[dict]:
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                _LEVEL_SELECT + " FROM levels WHERE user_id = %s ORDER BY id DESC",
                (user_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return _enrich_levels_pack_meta(rows)


def get_level(user_id: int, level_id: int) -> dict | None:
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                _LEVEL_SELECT + " FROM levels WHERE user_id = %s AND id = %s",
                (user_id, level_id),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return None
    # Sibling count needs full user list for this extract
    n = count_levels_for_extract(user_id, row.get("geofabrik_id") or "")
    enriched = _enrich_levels_pack_meta([row])[0]
    enriched["pack_levels_count"] = n
    enriched["pack_other_levels"] = max(0, n - 1) if row.get("geofabrik_id") else 0
    return enriched


def delete_level(user_id: int, level_id: int) -> bool:
    level = get_level(user_id, level_id)
    if not level:
        return False
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM levels WHERE id = %s AND user_id = %s", (level_id, user_id))
        conn.commit()
    finally:
        conn.close()
    d = level_dir(user_id, level_id)
    if d.exists():
        import shutil

        shutil.rmtree(d, ignore_errors=True)
    return True


def _update_level(level_id: int, **fields: Any) -> None:
    cols = []
    vals = []
    for k, v in fields.items():
        cols.append(f"{k} = %s")
        vals.append(v)
    cols.append("updated_at = NOW()")
    vals.append(level_id)
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE levels SET {', '.join(cols)} WHERE id = %s", vals)
        conn.commit()
    finally:
        conn.close()


def _refresh_network_stats(level_id: int, user_id: int) -> None:
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE levels SET
                  networks_count = sub.n,
                  networks_wifi = sub.wifi,
                  networks_bt = sub.bt,
                  networks_ble = sub.ble,
                  updated_at = NOW()
                FROM (
                  SELECT
                    COUNT(*)::int AS n,
                    COUNT(*) FILTER (WHERE network_type = 'WIFI')::int AS wifi,
                    COUNT(*) FILTER (WHERE network_type = 'BT')::int AS bt,
                    COUNT(*) FILTER (WHERE network_type = 'BLE')::int AS ble
                  FROM networks
                  WHERE user_id = %s
                    AND geom IS NOT NULL
                    AND ST_Within(geom, (SELECT bbox FROM levels WHERE id = %s))
                ) sub
                WHERE levels.id = %s
                """,
                (user_id, level_id, level_id),
            )
        conn.commit()
    finally:
        conn.close()


# Keep in sync with localize.DEFAULT_GPS_ACCURACY_M (avoid circular import)
_DEFAULT_GPS_ACCURACY_M = 15.0
# Unlock radius = GPS precision × 2 (per sample; null accuracy → default × 2)
EXPLORE_ACCURACY_FACTOR = 2.0
# GIST prefilter pad (~2 × default accuracy in degrees at mid-latitudes)
_EXPLORE_DEG_PAD = 0.00035


def _refresh_explored_from_observations(
    level_id: int, user_id: int, accuracy_factor: float = EXPLORE_ACCURACY_FACTOR
) -> dict[str, float | int]:
    """
    Unlock road segments within (sample.accuracy × factor) of any observation.
    Missing accuracy → DEFAULT_GPS_ACCURACY_M × factor (typically 30 m).
    Incremental: only flips locked → explored. Updates levels.explored_km / explored_pct.
    """
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE road_segments rs
                SET is_explored = TRUE,
                    explored_at = COALESCE(rs.explored_at, NOW()),
                    last_driven_at = NOW()
                WHERE rs.level_id = %s
                  AND rs.is_explored = FALSE
                  AND EXISTS (
                    SELECT 1
                    FROM signal_samples s
                    WHERE s.user_id = %s
                      AND s.geom && ST_Expand(rs.geom, %s)
                      AND ST_DWithin(
                        rs.geom::geography,
                        s.geom::geography,
                        GREATEST(
                          1.0,
                          COALESCE(NULLIF(s.accuracy, 0), %s) * %s
                        )
                      )
                  )
                """,
                (
                    level_id,
                    user_id,
                    _EXPLORE_DEG_PAD,
                    _DEFAULT_GPS_ACCURACY_M,
                    accuracy_factor,
                ),
            )
            newly = cur.rowcount
            row = _update_level_explored_stats(cur, level_id)
        conn.commit()
    finally:
        conn.close()

    return {
        "newly_explored": int(newly or 0),
        "explored_km": float(row[0] or 0) if row else 0.0,
        "explored_pct": float(row[1] or 0) if row else 0.0,
    }


def _read_level_explored_stats(cur, level_id: int):
    cur.execute(
        "SELECT explored_km, explored_pct FROM levels WHERE id = %s",
        (level_id,),
    )
    return cur.fetchone()


def _update_level_explored_stats(cur, level_id: int):
    # Completion % is Car (small_car) highways only (90% → region unlocked).
    # levels.road_km stays the full imported graph for size display.
    highways = sorted(profile_highways("small_car"))
    cur.execute(
        """
        UPDATE levels SET
          explored_km = sub.km,
          explored_pct = CASE
            WHEN COALESCE(sub.total_km, 0) > 0
            THEN LEAST(100.0, 100.0 * sub.km / sub.total_km)
            ELSE 0
          END,
          updated_at = NOW()
        FROM (
          SELECT
            COALESCE(SUM(length_m) FILTER (WHERE is_explored), 0) / 1000.0 AS km,
            COALESCE(SUM(length_m), 0) / 1000.0 AS total_km
          FROM road_segments
          WHERE level_id = %s AND highway = ANY(%s)
        ) sub
        WHERE levels.id = %s
        RETURNING explored_km, explored_pct
        """,
        (level_id, highways, level_id),
    )
    return cur.fetchone()


def _profile_progress_from_highway_rows(
    rows: list[dict],
) -> dict[str, dict[str, Any]]:
    """Fold highway × is_explored aggregates into per-profile km / % / complete."""
    by_hw: dict[str, dict[str, float]] = {}
    for row in rows:
        hw = str(row.get("highway") or "")
        bucket = by_hw.setdefault(hw, {"explored_m": 0.0, "locked_m": 0.0})
        length_m = float(row.get("length_m") or 0)
        if row.get("is_explored"):
            bucket["explored_m"] += length_m
        else:
            bucket["locked_m"] += length_m

    out: dict[str, dict[str, Any]] = {}
    for mode in ("big_car", "small_car", "bicycle", "foot"):
        explored_m = locked_m = 0.0
        for hw in profile_highways(mode):
            b = by_hw.get(hw)
            if not b:
                continue
            explored_m += b["explored_m"]
            locked_m += b["locked_m"]
        total_m = explored_m + locked_m
        explored_pct = (
            round(100.0 * explored_m / total_m, 2) if total_m > 0 else 0.0
        )
        out[mode] = {
            "explored_pct": explored_pct,
            "explored_km": round(explored_m / 1000.0, 2),
            "locked_km": round(locked_m / 1000.0, 2),
            "complete": is_complete(explored_pct),
            "label": profile_label(mode),
        }
    return out


# Same-OSM-way continuation only (metres). Cross-street stubs at junctions
# share endpoints too — never unlock those just because they touch.
_UNLOCK_TOUCH_M = 2.5
_UNLOCK_AHEAD_MAX_DEG = 40.0


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    Δλ = math.radians(lon2 - lon1)
    y = math.sin(Δλ) * math.cos(φ2)
    x = math.cos(φ1) * math.sin(φ2) - math.sin(φ1) * math.cos(φ2) * math.cos(Δλ)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _angle_diff_abs(a: float, b: float) -> float:
    return abs(((a - b + 540.0) % 360.0) - 180.0)


# An explored tile only pays "old tile" XP again once it hasn't been driven for
# this long. Every unlock pass stamps last_driven_at, so parking on a segment
# (or the "ahead" neighbour unlocked on the previous tick) never re-credits.
REVISIT_COOLDOWN_S = float(os.getenv("REVISIT_COOLDOWN_S", "1800"))


def _credit_tile_revisits(user_id: int | None, count: int) -> None:
    if user_id is None or count <= 0:
        return
    try:
        from achievements import record_tile_revisits

        record_tile_revisits(int(user_id), int(count))
    except Exception:
        pass


def _unlock_by_distance(
    level_id: int,
    lon: float,
    lat: float,
    *,
    radius_m: float,
    highways: list[str],
    user_id: int | None = None,
) -> dict[str, float | int]:
    """Unlock profile highways within radius_m of raw GPS (foot / bicycle)."""
    if radius_m <= 0 or not highways:
        return {
            "newly_explored": 0,
            "newly_explored_m": 0.0,
            "explored_km": 0.0,
            "explored_pct": 0.0,
            "segment_id": None,
            "unlocked_ids": [],
            "mode": "distance_skip",
            "radius_m": radius_m,
            "revisited": 0,
        }
    pad = max(0.0002, (radius_m + 20.0) / 111320.0)
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH pt AS (
                  SELECT ST_SetSRID(ST_MakePoint(%s, %s), 4326) AS g
                )
                SELECT rs.id, rs.is_explored,
                       (rs.is_explored AND (
                         rs.last_driven_at IS NULL
                         OR rs.last_driven_at < NOW() - make_interval(secs => %s)
                       )) AS revisit
                FROM road_segments rs
                CROSS JOIN pt
                WHERE rs.level_id = %s
                  AND rs.highway = ANY(%s)
                  AND rs.geom && ST_Expand(pt.g, %s)
                  AND ST_DWithin(rs.geom::geography, pt.g::geography, %s)
                """,
                (lon, lat, REVISIT_COOLDOWN_S, level_id, highways, pad, radius_m),
            )
            rows = list(cur.fetchall() or [])
            ids = [int(r["id"]) for r in rows]
            revisited = sum(1 for r in rows if r.get("revisit"))
            new_ids = [int(r["id"]) for r in rows if not r.get("is_explored")]
            if not ids:
                row = _read_level_explored_stats(cur, level_id)
                newly, newly_m = 0, 0.0
            else:
                cur.execute(
                    """
                    SELECT COUNT(*)::int AS n,
                           COALESCE(SUM(length_m), 0)::float AS m
                    FROM road_segments
                    WHERE level_id = %s
                      AND is_explored = FALSE
                      AND id = ANY(%s)
                    """,
                    (level_id, new_ids or [-1]),
                )
                before = cur.fetchone() or {}
                newly = int(before.get("n") or 0)
                newly_m = float(before.get("m") or 0.0)
                cur.execute(
                    """
                    UPDATE road_segments
                    SET is_explored = TRUE,
                        explored_at = COALESCE(explored_at, NOW()),
                        last_driven_at = NOW()
                    WHERE level_id = %s
                      AND id = ANY(%s)
                    """,
                    (level_id, ids),
                )
                row = (
                    _update_level_explored_stats(cur, level_id)
                    if newly
                    else _read_level_explored_stats(cur, level_id)
                )
        conn.commit()
    finally:
        conn.close()
    _credit_tile_revisits(user_id, revisited)
    if isinstance(row, dict):
        explored_km = float(row.get("explored_km") or 0)
        explored_pct = float(row.get("explored_pct") or 0)
    elif row:
        explored_km = float(row[0] or 0)
        explored_pct = float(row[1] or 0)
    else:
        explored_km = 0.0
        explored_pct = 0.0
    return {
        "newly_explored": newly,
        "newly_explored_m": newly_m,
        "explored_km": explored_km,
        "explored_pct": explored_pct,
        "segment_id": None,
        "unlocked_ids": ids,
        "mode": "distance",
        "radius_m": radius_m,
        "revisited": revisited,
    }


def unlock_near_point(
    level_id: int,
    lon: float,
    lat: float,
    accuracy_m: float | None = None,
    accuracy_factor: float = EXPLORE_ACCURACY_FACTOR,
    heading_deg: float | None = None,
    lateral_m: float | None = None,
    segment_id: int | None = None,
    profile: str | None = None,
    user_id: int | None = None,
) -> dict[str, float | int]:
    """
    Fog unlock for the active Navigate profile.

    Car (big_car / small_car): snapped segment + same-OSM-way ahead continuation.
    Foot / bicycle: unlock profile highways within accuracy × factor of raw GPS.
    """
    mode = normalize_profile(profile)
    highways = sorted(profile_highways(mode))

    if not profile_uses_road_snap(mode):
        acc = float(accuracy_m) if accuracy_m and accuracy_m > 0 else _DEFAULT_GPS_ACCURACY_M
        if lateral_m is not None and float(lateral_m) > 0:
            radius = float(lateral_m)
        else:
            radius = acc * float(accuracy_factor)
        return _unlock_by_distance(
            level_id,
            lon,
            lat,
            radius_m=radius,
            highways=highways,
            user_id=user_id,
        )

    # Car: snap corridor only
    if segment_id is None:
        return {
            "newly_explored": 0,
            "newly_explored_m": 0.0,
            "explored_km": 0.0,
            "explored_pct": 0.0,
            "segment_id": None,
            "unlocked_ids": [],
            "mode": "skip_no_snap",
        }

    sid = int(segment_id)
    ids: list[int] = [sid]
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, osm_id,
                       ST_Y(ST_StartPoint(geom)) AS slat,
                       ST_X(ST_StartPoint(geom)) AS slon,
                       ST_Y(ST_EndPoint(geom)) AS elat,
                       ST_X(ST_EndPoint(geom)) AS elon
                FROM road_segments
                WHERE level_id = %s AND id = %s
                """,
                (level_id, sid),
            )
            cur_seg = cur.fetchone()
            if not cur_seg:
                return {
                    "newly_explored": 0,
                    "newly_explored_m": 0.0,
                    "explored_km": 0.0,
                    "explored_pct": 0.0,
                    "segment_id": sid,
                    "unlocked_ids": [],
                    "mode": "missing_segment",
                }

            heading = float(heading_deg) % 360.0 if heading_deg is not None else None
            osm_id = cur_seg.get("osm_id")
            # Only look ahead along the same OSM way — junction cross-streets
            # share endpoints but have a different osm_id.
            if heading is not None and osm_id is not None:
                cur.execute(
                    """
                    SELECT n.id,
                           ST_Y(ST_StartPoint(n.geom)) AS slat,
                           ST_X(ST_StartPoint(n.geom)) AS slon,
                           ST_Y(ST_EndPoint(n.geom)) AS elat,
                           ST_X(ST_EndPoint(n.geom)) AS elon
                    FROM road_segments c
                    JOIN road_segments n
                      ON n.level_id = c.level_id
                     AND n.id <> c.id
                     AND n.osm_id = c.osm_id
                    WHERE c.level_id = %s AND c.id = %s
                      AND (
                        ST_DWithin(
                          ST_StartPoint(c.geom)::geography,
                          ST_StartPoint(n.geom)::geography, %s
                        )
                        OR ST_DWithin(
                          ST_StartPoint(c.geom)::geography,
                          ST_EndPoint(n.geom)::geography, %s
                        )
                        OR ST_DWithin(
                          ST_EndPoint(c.geom)::geography,
                          ST_StartPoint(n.geom)::geography, %s
                        )
                        OR ST_DWithin(
                          ST_EndPoint(c.geom)::geography,
                          ST_EndPoint(n.geom)::geography, %s
                        )
                      )
                    """,
                    (
                        level_id,
                        sid,
                        _UNLOCK_TOUCH_M,
                        _UNLOCK_TOUCH_M,
                        _UNLOCK_TOUCH_M,
                        _UNLOCK_TOUCH_M,
                    ),
                )
                neighbours = cur.fetchall() or []
                ahead_id = None
                ahead_err = 1e9
                c_slat, c_slon = float(cur_seg["slat"]), float(cur_seg["slon"])
                c_elat, c_elon = float(cur_seg["elat"]), float(cur_seg["elon"])

                for n in neighbours:
                    nid = int(n["id"])
                    n_slat, n_slon = float(n["slat"]), float(n["slon"])
                    n_elat, n_elon = float(n["elat"]), float(n["elon"])
                    brgs: list[float] = []
                    for cy, cx, ny, nx, fy, fx in (
                        (c_slat, c_slon, n_slat, n_slon, n_elat, n_elon),
                        (c_slat, c_slon, n_elat, n_elon, n_slat, n_slon),
                        (c_elat, c_elon, n_slat, n_slon, n_elat, n_elon),
                        (c_elat, c_elon, n_elat, n_elon, n_slat, n_slon),
                    ):
                        if haversine_m(cy, cx, ny, nx) <= _UNLOCK_TOUCH_M:
                            brgs.append(_bearing_deg(cy, cx, fy, fx))
                    if not brgs:
                        continue
                    err_fwd = min(_angle_diff_abs(b, heading) for b in brgs)
                    if err_fwd < ahead_err and err_fwd <= _UNLOCK_AHEAD_MAX_DEG:
                        ahead_err = err_fwd
                        ahead_id = nid

                if ahead_id is not None and ahead_id not in ids:
                    ids.append(int(ahead_id))

            cur.execute(
                """
                SELECT COUNT(*) FILTER (WHERE NOT is_explored)::int AS n,
                       COALESCE(SUM(length_m) FILTER (WHERE NOT is_explored), 0)::float AS m,
                       COUNT(*) FILTER (
                         WHERE is_explored AND (
                           last_driven_at IS NULL
                           OR last_driven_at < NOW() - make_interval(secs => %s)
                         )
                       )::int AS revisit
                FROM road_segments
                WHERE level_id = %s
                  AND id = ANY(%s)
                """,
                (REVISIT_COOLDOWN_S, level_id, ids),
            )
            before = cur.fetchone() or {}
            newly = int(before.get("n") or 0)
            newly_m = float(before.get("m") or 0.0)
            revisited = int(before.get("revisit") or 0)
            # Always stamp last_driven_at; explored_at only on first unlock
            cur.execute(
                """
                UPDATE road_segments
                SET is_explored = TRUE,
                    explored_at = COALESCE(explored_at, NOW()),
                    last_driven_at = NOW()
                WHERE level_id = %s
                  AND id = ANY(%s)
                """,
                (level_id, ids),
            )
            row = (
                _update_level_explored_stats(cur, level_id)
                if newly
                else _read_level_explored_stats(cur, level_id)
            )
        conn.commit()
    finally:
        conn.close()
    _credit_tile_revisits(user_id, revisited)
    if isinstance(row, dict):
        explored_km = float(row.get("explored_km") or 0)
        explored_pct = float(row.get("explored_pct") or 0)
    elif row:
        explored_km = float(row[0] or 0)
        explored_pct = float(row[1] or 0)
    else:
        explored_km = 0.0
        explored_pct = 0.0
    return {
        "newly_explored": newly,
        "newly_explored_m": newly_m,
        "explored_km": explored_km,
        "explored_pct": explored_pct,
        "segment_id": sid,
        "unlocked_ids": ids,
        "mode": "snap_segment",
        "revisited": revisited,
    }


def local_place_bbox(place_query: str) -> list[float] | None:
    """Return [minlon, minlat, maxlon, maxlat] from the offline cities DB."""
    if not place_query:
        return None
    try:
        from cities_db import lookup_city_by_label

        hit = lookup_city_by_label(place_query)
        if hit and hit.get("bbox"):
            return list(hit["bbox"])
    except Exception:
        return None
    return None


def process_level_job(user_id: int, level_id: int, progress_cb=None) -> dict:
    """
    progress_cb(progress: float 0-1, stage: str, message: str, eta_seconds: float|None)
    Stages: download | extract | roads | finish
    """
    import time

    def report(progress: float, stage: str, message: str, eta: float | None = None):
        if progress_cb:
            progress_cb(progress, stage, message, eta)

    t0 = time.monotonic()
    level = get_level(user_id, level_id)
    if not level:
        raise ValueError("Level not found")

    # --- Map file: prefer shared PBF from prepare (already downloaded) ---
    _update_level(level_id, status="processing", error=None)
    level_pbf = level_dir(user_id, level_id) / "extract.osm.pbf"
    dest = level_pbf
    size = None
    from admin_areas import pbf_path_for_extract

    shared = pbf_path_for_extract(level.get("geofabrik_id") or "")
    if shared.exists() and shared.stat().st_size > 1000:
        # Use the kept regional pack in place — no copy, no download stage
        dest = shared
        size = shared.stat().st_size
        report(0.05, "extract", "Using saved regional map pack…", 5)
    elif level_pbf.exists() and level_pbf.stat().st_size > 1000:
        dest = level_pbf
        size = level_pbf.stat().st_size
        report(0.05, "extract", "Using existing map file…", 5)
    else:
        report(0.02, "download", "Downloading map data…", None)
        dl_start = time.monotonic()

        def on_dl(frac, done, total):
            p = 0.02 + 0.40 * max(0.0, min(1.0, frac))
            eta = None
            elapsed = time.monotonic() - dl_start
            if frac > 0.02 and elapsed > 0.5:
                eta = (elapsed / frac) * (1.0 - frac)
            mb = (done or 0) / (1024 * 1024)
            msg = f"Downloading map data… {mb:.0f} MB"
            if total:
                msg = f"Downloading map data… {mb:.0f} / {total / (1024 * 1024):.0f} MB"
            report(p, "download", msg, eta)

        size = download_pbf(level["pbf_url"], level_pbf, progress_cb=on_dl)
        dest = level_pbf

    _update_level(level_id, status="processing", disk_bytes=size)

    # Full playable graph once — Navigate mode filters highways at routing time
    allowed = all_playable_highways()
    place_bbox = level.get("bbox")
    boundary = level.get("boundary")
    if isinstance(boundary, str):
        try:
            boundary = json.loads(boundary)
        except Exception:
            boundary = None
    if isinstance(place_bbox, (list, tuple)) and len(place_bbox) == 4:
        place_bbox = [float(x) for x in place_bbox]
    elif not boundary:
        place_bbox = local_place_bbox(level.get("place_query") or level.get("name") or "")
        if place_bbox:
            minlon, minlat, maxlon, maxlat = place_bbox
            conn = connect()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE levels SET bbox = ST_MakeEnvelope(%s,%s,%s,%s,4326), updated_at = NOW()
                        WHERE id = %s
                        """,
                        (minlon, minlat, maxlon, maxlat, level_id),
                    )
                conn.commit()
            finally:
                conn.close()

    clip_bbox = place_bbox
    if not clip_bbox and boundary:
        clip_bbox = _geom_bbox(boundary)
    geom_bb = _geom_bbox(boundary) if boundary else None

    # --- Extract / detect roads (bbox-filtered — never scan whole region into RAM) ---
    report(0.08, "extract", "Finding roads in your area…", 90)
    ways = []
    try:
        ways = _extract_ways_osmium(dest, allowed, bbox=clip_bbox)
        report(0.45, "extract", f"Clipping {len(ways):,} roads to boundary…", 20)
        if boundary and ways:
            workers = min(_BUILD_WORKERS, max(1, len(ways) // 500 or 1))
            chunks = _chunked(ways, workers)
            clipped: list = []
            done_chunks = 0
            try:
                with _executor(workers) as pool:
                    futures = [
                        pool.submit(_clip_ways_chunk, ch, boundary, geom_bb)
                        for ch in chunks
                    ]
                    for fut in as_completed(futures):
                        clipped.extend(fut.result())
                        done_chunks += 1
                        report(
                            0.45 + 0.15 * (done_chunks / max(len(chunks), 1)),
                            "extract",
                            f"Clipping roads… {done_chunks}/{len(chunks)} cores",
                            None,
                        )
            except Exception:
                clipped = _clip_ways_chunk(ways, boundary, geom_bb)
            ways = clipped
        report(0.62, "extract", f"Found {len(ways):,} roads in area", 5)
    except Exception:
        bbox = clip_bbox
        if not bbox:
            feat = resolve_feature(level["geofabrik_id"])
            bbox = feat.get("bbox") if feat else None
        if not bbox:
            raise
        report(0.40, "extract", "Fetching roads for your area…", 120)
        ways = _extract_ways_overpass([float(x) for x in bbox], allowed)
        if boundary:
            ways = [
                (osm_id, hw, name, coords)
                for osm_id, hw, name, coords in ways
                if way_intersects_boundary(coords, boundary, geom_bbox=geom_bb)
            ]

    # --- Segmentize (parallel CPU) then single-threaded DB insert ---
    _update_level(level_id, status="segmentizing")
    report(0.65, "roads", f"Building playable roads ({len(ways):,} ways)…", 60)
    total_m = 0.0
    seg_count = 0
    all_rows: list[tuple] = []
    if ways:
        workers = min(_BUILD_WORKERS, max(1, len(ways) // 200 or 1))
        chunks = _chunked(ways, workers)
        done_chunks = 0
        try:
            with _executor(workers) as pool:
                futures = [
                    pool.submit(_segmentize_ways_chunk, ch, level_id, boundary)
                    for ch in chunks
                ]
                for fut in as_completed(futures):
                    rows, meters = fut.result()
                    all_rows.extend(rows)
                    total_m += meters
                    done_chunks += 1
                    report(
                        0.65 + 0.20 * (done_chunks / max(len(chunks), 1)),
                        "roads",
                        f"Building segments… {done_chunks}/{len(chunks)} cores",
                        None,
                    )
        except Exception:
            rows, meters = _segmentize_ways_chunk(ways, level_id, boundary)
            all_rows = rows
            total_m = meters

    report(0.86, "roads", f"Writing {len(all_rows):,} segments…", 20)
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM road_segments WHERE level_id = %s", (level_id,))
            flush_n = 2000
            for i in range(0, len(all_rows), flush_n):
                chunk = all_rows[i : i + flush_n]
                _flush_segments(cur, chunk)
                seg_count += len(chunk)
                if all_rows:
                    report(
                        0.86 + 0.08 * ((i + len(chunk)) / len(all_rows)),
                        "roads",
                        f"Writing segments… {seg_count:,}/{len(all_rows):,}",
                        None,
                    )
            cur.execute(
                """
                UPDATE levels SET
                  status = 'ready',
                  road_km = %s,
                  disk_bytes = %s,
                  error = NULL,
                  updated_at = NOW()
                WHERE id = %s
                """,
                (total_m / 1000.0, size, level_id),
            )
        conn.commit()
    finally:
        conn.close()

    # Belt-and-suspenders: drop any leftover midpoints outside the polygon
    if boundary:
        report(0.94, "roads", "Clipping roads to level border…", 5)
        clip_road_segments_to_boundary(level_id)

    # Addresses are NOT on the critical path — enqueue after roads are ready so
    # Navigate / Valhalla can start immediately. Geocode fills in later too.
    report(0.96, "finish", "Counting networks in area…", 5)
    _refresh_network_stats(level_id, user_id)
    report(0.98, "finish", "Matching observations to roads…", 3)
    _refresh_explored_from_observations(level_id, user_id)

    addr_job_id = None
    try:
        from jobs import enqueue_job

        job = enqueue_job(
            user_id,
            "level_addresses",
            {
                "level_id": level_id,
                "pbf": str(dest),
                "bbox": list(clip_bbox) if clip_bbox else None,
                "priority": 60,
            },
        )
        addr_job_id = job.get("id")
    except Exception:
        addr_job_id = None

    # Clip/seed Valhalla to this level's city/district only — never the full region.
    valhalla_out = None
    try:
        from valhalla_prep import prepare_valhalla_for_level

        report(0.99, "finish", "Starting Valhalla routing…", 30)
        valhalla_out = prepare_valhalla_for_level(
            user_id, level_id, restart=True, force=False
        )
    except Exception as exc:
        # Retry once with force (re-clip bbox). Do not fall back to tiling the
        # whole regional Geofabrik pack — that is what made builds crawl.
        try:
            from valhalla_prep import prepare_valhalla_for_level

            valhalla_out = prepare_valhalla_for_level(
                user_id, level_id, restart=True, force=True
            )
            valhalla_out = {"retried": True, "first_error": str(exc), **valhalla_out}
        except Exception as exc2:
            valhalla_out = {"ok": False, "detail": str(exc), "retry_error": str(exc2)}

    report(1.0, "done", "Level ready — addresses fill in the background", 0)
    return {
        "level_id": level_id,
        "segments": seg_count,
        "road_km": total_m / 1000.0,
        "disk_bytes": size,
        "ways": len(ways),
        "valhalla": valhalla_out,
        "addresses": 0,
        "address_job_id": addr_job_id,
        "stage": "done",
    }


def build_level_addresses_job(
    user_id: int,
    level_id: int,
    *,
    pbf: str | None = None,
    bbox: list | None = None,
    progress_cb=None,
) -> dict:
    """Background: OSM addr:* pack for reverse-geocode (after level is ready)."""
    from address_index import build_level_address_pack
    from pathlib import Path

    def report(progress: float, stage: str, message: str, eta: float | None = None):
        if progress_cb:
            progress_cb(progress, stage, message, eta)

    level = get_level(user_id, level_id)
    if not level:
        raise ValueError("Level not found")

    dest = Path(pbf) if pbf else None
    if dest is None or not dest.exists():
        from admin_areas import pbf_path_for_extract

        shared = pbf_path_for_extract(level.get("geofabrik_id") or "")
        level_pbf = level_dir(user_id, level_id) / "extract.osm.pbf"
        if shared.exists():
            dest = shared
        elif level_pbf.exists():
            dest = level_pbf
        else:
            raise ValueError("No PBF available for address pack")

    clip_bbox = bbox or level.get("bbox")
    boundary = level.get("boundary")
    report(0.1, "addresses", "Building local address pack…", None)

    def _addr_prog(msg: str):
        report(0.4, "addresses", msg, None)

    addr_info = build_level_address_pack(
        user_id,
        level_id,
        dest,
        bbox=clip_bbox,
        boundary=boundary if isinstance(boundary, dict) else None,
        progress=_addr_prog,
    )
    count = int(addr_info.get("count") or 0)
    report(1.0, "done", f"Saved {count:,} addresses for this level", 0)

    # Now reverse-geocode any networks still missing addresses
    try:
        from jobs import enqueue_job

        enqueue_job(
            user_id,
            "geocode",
            {"only_missing": True, "priority": 50},
        )
    except Exception:
        pass

    return {"level_id": level_id, "addresses": count, "stage": "done"}


def search_level_places(query: str, limit: int = 8) -> list[dict]:
    from level_places import search_level_places as _search

    return _search(query, limit=limit)


def set_level_default_profile(user_id: int, level_id: int, profile: str | None) -> None:
    """Persist last-used Navigate mode on the level (not a map rebuild input)."""
    p = normalize_profile(profile)
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE levels SET profile = %s, updated_at = NOW()
                WHERE id = %s AND user_id = %s
                """,
                (p, level_id, user_id),
            )
        conn.commit()
    finally:
        conn.close()


# Drive refetches the road map every few seconds; the observation probe scans
# every locked segment against signal_samples, so run it at most this often.
_OBSERVATION_REFRESH_S = 60.0
_observation_refresh_at: dict[tuple[int, int], float] = {}
_boundary_clip_done: set[int] = set()


def _coerce_multilinestring(geom: Any) -> dict[str, Any]:
    """
    MapLibre fog layers only draw LineString / MultiLineString. ST_Collect can
    return a GeometryCollection (or a JSON string) — coerce so roads actually
    paint when the tile counter already updated.
    """
    empty: dict[str, Any] = {"type": "MultiLineString", "coordinates": []}
    if geom is None:
        return empty
    if isinstance(geom, (bytes, bytearray)):
        try:
            geom = geom.decode("utf-8")
        except Exception:
            return empty
    if isinstance(geom, str):
        try:
            geom = json.loads(geom)
        except json.JSONDecodeError:
            return empty
    if not isinstance(geom, dict):
        return empty

    def _parts(g: dict) -> list:
        t = g.get("type")
        if t == "LineString":
            c = g.get("coordinates") or []
            return [c] if len(c) >= 2 else []
        if t == "MultiLineString":
            return [c for c in (g.get("coordinates") or []) if c and len(c) >= 2]
        if t == "GeometryCollection":
            out: list = []
            for child in g.get("geometries") or []:
                if isinstance(child, dict):
                    out.extend(_parts(child))
            return out
        return []

    coords = _parts(geom)
    return {"type": "MultiLineString", "coordinates": coords}


def get_level_road_map(
    user_id: int,
    level_id: int,
    *,
    profile: str | None = None,
) -> dict | None:
    """
    Discover view payload: locked vs explored road grids as MultiLineString GeoJSON.
    Optional profile filters to that mode's highways (Navigate / Progress).
    Explored flags stay shared; % is scoped to the filtered set when profile is set.
    Always includes by_profile stats for all modes; completion = Car (small_car) ≥ 90%.
    """
    level = get_level(user_id, level_id)
    if not level:
        return None

    if level.get("status") == "ready":
        # One-shot repair for legacy builds that kept whole OSM ways past the border
        if level_id not in _boundary_clip_done:
            try:
                clip_road_segments_to_boundary(level_id)
            except Exception:
                pass
            _boundary_clip_done.add(level_id)
            level = get_level(user_id, level_id) or level
        now = time.monotonic()
        key = (user_id, level_id)
        if now - _observation_refresh_at.get(key, -1e9) >= _OBSERVATION_REFRESH_S:
            _observation_refresh_at[key] = now
            _refresh_explored_from_observations(level_id, user_id)
            level = get_level(user_id, level_id) or level

    mode = normalize_profile(profile) if profile else None
    highways = sorted(profile_highways(mode)) if mode else None

    # Force linework MultiLineString: ST_Collect alone can yield GeometryCollection
    # which MapLibre line layers silently skip (tile counts still update).
    geom_sql = """
      COALESCE(
        ST_AsGeoJSON(
          ST_CollectionExtract(ST_Collect(ST_Force2D(geom)), 2)
        )::json,
        '{"type":"MultiLineString","coordinates":[]}'::json
      )
    """

    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  highway,
                  is_explored,
                  COALESCE(SUM(length_m), 0)::float AS length_m
                FROM road_segments
                WHERE level_id = %s
                GROUP BY highway, is_explored
                """,
                (level_id,),
            )
            hwy_rows = cur.fetchall()

            if highways:
                cur.execute(
                    f"""
                    SELECT
                      is_explored,
                      COUNT(*)::int AS n,
                      COALESCE(SUM(length_m), 0)::float AS length_m,
                      {geom_sql} AS geom
                    FROM road_segments
                    WHERE level_id = %s AND highway = ANY(%s)
                    GROUP BY is_explored
                    """,
                    (level_id, highways),
                )
            else:
                cur.execute(
                    f"""
                    SELECT
                      is_explored,
                      COUNT(*)::int AS n,
                      COALESCE(SUM(length_m), 0)::float AS length_m,
                      {geom_sql} AS geom
                    FROM road_segments
                    WHERE level_id = %s
                    GROUP BY is_explored
                    """,
                    (level_id,),
                )
            rows = cur.fetchall()
    finally:
        conn.close()

    by_profile = _profile_progress_from_highway_rows(hwy_rows)
    small = by_profile.get("small_car") or {}
    completion_pct = float(small.get("explored_pct") or 0.0)
    completion_done = bool(small.get("complete"))

    locked = {"type": "MultiLineString", "coordinates": []}
    explored = {"type": "MultiLineString", "coordinates": []}
    locked_n = explored_n = 0
    locked_m = explored_m = 0.0
    for row in rows:
        geom = _coerce_multilinestring(row.get("geom"))
        if row["is_explored"]:
            explored = geom
            explored_n = row["n"]
            explored_m = float(row["length_m"] or 0)
        else:
            locked = geom
            locked_n = row["n"]
            locked_m = float(row["length_m"] or 0)

    total_m = locked_m + explored_m
    if mode:
        explored_pct = (
            round(100.0 * explored_m / total_m, 2) if total_m > 0 else 0.0
        )
    else:
        # No filter: region completion % (Car / small_car), not full-graph fraction
        explored_pct = completion_pct

    bbox = level.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        bbox = [float(x) for x in bbox]
    else:
        bbox = None

    return {
        "level": {
            "id": level["id"],
            "name": level["name"],
            "status": level["status"],
            "profile": mode or level.get("profile"),
            "profile_filter": mode,
            "explored_pct": explored_pct,
            "completion_pct": completion_pct,
            "complete": completion_done,
            "road_km": round(total_m / 1000.0, 2) if mode else level.get("road_km"),
        },
        "bbox": bbox,
        "boundary": level.get("boundary"),
        "locked": locked,
        "explored": explored,
        "by_profile": by_profile,
        "stats": {
            "locked_segments": locked_n,
            "explored_segments": explored_n,
            "total_segments": int(locked_n or 0) + int(explored_n or 0),
            "locked_km": round(locked_m / 1000.0, 2),
            "explored_km": round(explored_m / 1000.0, 2),
        },
    }


def _flush_segments(cur, batch: list[tuple]) -> None:
    from psycopg2.extras import execute_values

    execute_values(
        cur,
        """
        INSERT INTO road_segments (level_id, osm_id, highway, name, geom, length_m)
        VALUES %s
        """,
        batch,
        template="(%s,%s,%s,%s,ST_GeomFromText(%s,4326),%s)",
        page_size=500,
    )


def search_geofabrik(query: str) -> list[dict]:
    return search_places(query)
