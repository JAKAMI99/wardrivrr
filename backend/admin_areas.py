"""
Local index of OSM administrative boundaries (cities + districts).

Built once per Geofabrik extract from its .osm.pbf (pyosmium) into
data/cities/admin_areas.sqlite. Lookups are pure disk reads — no Overpass.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "cities" / "admin_areas.sqlite"
PBF_DIR = ROOT / "data" / "pbf"

MIN_ADMIN_LEVEL = 4
MAX_ADMIN_LEVEL = 10
# Larger areas are states/regions, never a playable city (city-states are smaller)
MAX_SPAN_DEG = 1.2


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS areas (
            osm_type TEXT NOT NULL,
            osm_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            admin_level INTEGER NOT NULL,
            minlon REAL NOT NULL, minlat REAL NOT NULL,
            maxlon REAL NOT NULL, maxlat REAL NOT NULL,
            clon REAL NOT NULL, clat REAL NOT NULL,
            geojson TEXT NOT NULL,
            extract_id TEXT,
            PRIMARY KEY (osm_type, osm_id)
        );
        CREATE INDEX IF NOT EXISTS areas_bbox_idx ON areas(minlon, maxlon, minlat, maxlat);
        CREATE INDEX IF NOT EXISTS areas_level_idx ON areas(admin_level);
        CREATE TABLE IF NOT EXISTS extracts (
            extract_id TEXT PRIMARY KEY,
            indexed_at REAL NOT NULL,
            n_areas INTEGER NOT NULL
        );
        """
    )
    return conn


def db_available() -> bool:
    if not DB_PATH.exists():
        return False
    try:
        conn = _connect()
        try:
            return conn.execute("SELECT 1 FROM areas LIMIT 1").fetchone() is not None
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def indexed_extracts() -> list[str]:
    if not DB_PATH.exists():
        return []
    conn = _connect()
    try:
        return [r["extract_id"] for r in conn.execute("SELECT extract_id FROM extracts")]
    finally:
        conn.close()


def is_extract_indexed(extract_id: str) -> bool:
    eid = (extract_id or "").strip()
    if not eid:
        return False
    return eid in indexed_extracts() or eid.split("/")[-1] in {
        e.split("/")[-1] for e in indexed_extracts()
    }


def pbf_path_for_extract(extract_id: str) -> Path:
    """Canonical on-disk path for a Geofabrik extract id."""
    safe = (extract_id or "").strip().replace("/", "_")
    return PBF_DIR / f"{safe}.osm.pbf"


def ensure_extract_indexed(extract_id: str) -> bool:
    """
    If this extract is not indexed yet but a local PBF exists, index it.
    Returns True when the extract is available afterward.
    Does not download — use prepare_extract / build_admin_areas for that.
    """
    eid = (extract_id or "").strip()
    if not eid:
        return False
    if is_extract_indexed(eid):
        return True
    pbf = pbf_path_for_extract(eid)
    if not pbf.exists():
        short = eid.split("/")[-1]
        alt = PBF_DIR / f"{short}.osm.pbf"
        if alt.exists():
            pbf = alt
            eid = short
        else:
            return False
    index_pbf(pbf, eid)
    return True


def prepare_extract(
    extract_id: str,
    *,
    pbf_url: str | None = None,
    progress_cb=None,
) -> dict:
    """
    Ensure regional PBF is on disk (kept forever) and admin areas are indexed.

    progress_cb(progress 0-1, stage, message, eta_seconds|None)
    """
    from geofabrik import download_pbf, resolve_feature

    eid = (extract_id or "").strip()
    if not eid:
        raise ValueError("extract_id required")

    def report(p, stage, msg, eta=None):
        if progress_cb:
            progress_cb(p, stage, msg, eta)

    feat = resolve_feature(eid) or {}
    url = pbf_url or feat.get("pbf_url")
    if not url:
        raise ValueError(f"Unknown Geofabrik extract: {eid}")

    pbf = pbf_path_for_extract(eid)
    downloaded = False
    if pbf.exists() and pbf.stat().st_size > 1000:
        report(0.45, "ready", "Map pack already on disk…", 5)
    else:
        report(0.02, "download", "Downloading regional map data…", None)
        t0 = time.monotonic()

        def on_dl(frac, done, total):
            p = 0.02 + 0.55 * max(0.0, min(1.0, frac))
            eta = None
            elapsed = time.monotonic() - t0
            if frac > 0.02 and elapsed > 0.5:
                eta = (elapsed / frac) * (1.0 - frac)
            mb = (done or 0) / (1024 * 1024)
            msg = f"Downloading map data… {mb:.0f} MB"
            if total:
                msg = f"Downloading map data… {mb:.0f} / {total / (1024 * 1024):.0f} MB"
            report(p, "download", msg, eta)

        download_pbf(url, pbf, progress_cb=on_dl)
        downloaded = True

    if not is_extract_indexed(eid):
        report(0.60, "index", "Indexing city & district outlines…", 45)
        index_pbf(pbf, eid, progress=lambda msg: report(0.85, "index", msg, 5))
        report(0.95, "index", "Outlines ready…", 2)
    else:
        report(0.70, "index", "Outlines already indexed…", 2)
        report(0.92, "index", "Loading city & districts…", 1)

    # First regional pack → seed data/valhalla/active.osm.pbf and full tile rebuild.
    # Packs keep names like Arnsberg….osm.pbf under data/pbf/; Valhalla reads active.osm.pbf.
    valhalla_out = None
    try:
        from valhalla_prep import active_pbf_ready, ensure_valhalla_after_regional_pbf

        if downloaded or not active_pbf_ready():
            valhalla_out = ensure_valhalla_after_regional_pbf(
                pbf, force_seed=bool(downloaded), restart=True
            )
    except Exception as exc:
        valhalla_out = {"ok": False, "detail": str(exc)}

    report(1.0, "done", "Ready", 0)
    return {
        "extract_id": eid,
        "pbf_path": str(pbf),
        "downloaded": downloaded,
        "size_bytes": pbf.stat().st_size if pbf.exists() else None,
        "valhalla": valhalla_out,
        "map_pack": {
            "id": feat.get("id") or eid,
            "name": feat.get("name"),
            "pbf_url": url,
            "size_bytes": feat.get("size_bytes") or (pbf.stat().st_size if pbf.exists() else None),
        },
    }


def place_options_for_city(
    *,
    lat: float,
    lon: float,
    name: str | None,
    population: int | None = None,
    bbox: list[float] | None = None,
) -> dict:
    """Whole city + districts (with area_km2). City includes boundary; districts do not."""
    from city_boundaries import city_may_have_parts

    city = find_city(lat, lon, name)
    if not city:
        return {"city": None, "districts": [], "skipped_reason": "not_indexed"}

    city_area = geom_area_km2(city["boundary"])
    city_out = {
        **{k: v for k, v in city.items() if k != "boundary"},
        "boundary": city["boundary"],
        "area_km2": city_area,
        "place_type": "city",
    }

    districts_out: list[dict] = []
    if city_may_have_parts(
        population=population,
        bbox=bbox or city.get("bbox"),
        area_km2=city_area,
    ):
        _level, districts = find_districts(city)
        for d in districts:
            full = get_area(d["osm_id"], d.get("osm_type") or "relation") or d
            geom = full.get("boundary")
            districts_out.append(
                {
                    "osm_type": full.get("osm_type") or d.get("osm_type"),
                    "osm_id": full["osm_id"],
                    "name": _clean_district_name(full["name"]),
                    "admin_level": full["admin_level"],
                    "bbox": full["bbox"],
                    "lat": full["lat"],
                    "lon": full["lon"],
                    "area_km2": geom_area_km2(geom),
                    "place_type": "district",
                    "part_label": "District",
                }
            )

    return {"city": city_out, "districts": districts_out, "skipped_reason": None}


# --- geometry helpers -------------------------------------------------------


def _point_in_ring(lon: float, lat: float, ring: list) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-15) + xi
        ):
            inside = not inside
        j = i
    return inside


def point_in_geom(lon: float, lat: float, geom: dict) -> bool:
    gtype = geom.get("type")
    coords = geom.get("coordinates") or []
    polys = [coords] if gtype == "Polygon" else coords if gtype == "MultiPolygon" else []
    for poly in polys:
        if poly and _point_in_ring(lon, lat, poly[0]) and not any(
            _point_in_ring(lon, lat, hole) for hole in poly[1:]
        ):
            return True
    return False


def _ring_area(ring: list) -> float:
    s = 0.0
    for i in range(len(ring) - 1):
        s += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
    return s / 2.0


def _ring_centroid(ring: list) -> tuple[float, float] | None:
    a = _ring_area(ring)
    if abs(a) < 1e-12:
        return None
    cx = cy = 0.0
    for i in range(len(ring) - 1):
        f = ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
        cx += (ring[i][0] + ring[i + 1][0]) * f
        cy += (ring[i][1] + ring[i + 1][1]) * f
    return cx / (6 * a), cy / (6 * a)


def _label_point(geom: dict) -> tuple[float, float]:
    """(lon, lat) inside the largest outer ring when possible."""
    coords = geom["coordinates"]
    polys = [coords] if geom["type"] == "Polygon" else coords
    outer = max((p[0] for p in polys), key=lambda r: abs(_ring_area(r)))
    c = _ring_centroid(outer)
    if c and point_in_geom(c[0], c[1], geom):
        return c
    # Concave shape: fall back to a vertex-average, then any vertex
    ax = sum(p[0] for p in outer) / len(outer)
    ay = sum(p[1] for p in outer) / len(outer)
    if point_in_geom(ax, ay, geom):
        return ax, ay
    return outer[0][0], outer[0][1]


def _bbox(geom: dict) -> list[float]:
    coords = geom["coordinates"]
    polys = [coords] if geom["type"] == "Polygon" else coords
    lons = [p[0] for poly in polys for p in poly[0]]
    lats = [p[1] for poly in polys for p in poly[0]]
    return [min(lons), min(lats), max(lons), max(lats)]


def geom_area_km2(geom: dict | None) -> float | None:
    """Approximate geodesic area of a Polygon / MultiPolygon (good enough for UI)."""
    if not geom:
        return None

    def _ring_m2(ring: list) -> float:
        if len(ring) < 4:
            return 0.0
        lat0 = sum(p[1] for p in ring[:-1]) / max(len(ring) - 1, 1)
        m_lat = 111_132.0
        m_lon = 111_320.0 * max(0.2, math.cos(math.radians(lat0)))
        pts = [(p[0] * m_lon, p[1] * m_lat) for p in ring]
        s = 0.0
        for i in range(len(pts) - 1):
            s += pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1]
        return abs(s) / 2.0

    def _poly_m2(poly: list) -> float:
        if not poly:
            return 0.0
        a = _ring_m2(poly[0])
        for hole in poly[1:]:
            a -= _ring_m2(hole)
        return max(0.0, a)

    gtype = geom.get("type")
    coords = geom.get("coordinates") or []
    if gtype == "Polygon":
        m2 = _poly_m2(coords)
    elif gtype == "MultiPolygon":
        m2 = sum(_poly_m2(p) for p in coords)
    else:
        return None
    return round(m2 / 1_000_000.0, 2)


# --- indexing ---------------------------------------------------------------


def index_pbf(pbf_path: Path, extract_id: str, progress=print) -> int:
    """Extract admin_level 4–10 boundaries from a Geofabrik PBF into the local index."""
    import osmium

    t0 = time.monotonic()
    fp = (
        osmium.FileProcessor(str(pbf_path))
        .with_areas(osmium.filter.TagFilter(("boundary", "administrative")))
        .with_filter(osmium.filter.EntityFilter(osmium.osm.AREA))
        .with_filter(osmium.filter.TagFilter(("boundary", "administrative")))
    )
    rows = []
    for area in fp:
        tags = area.tags
        name = tags.get("name") or tags.get("name:en")
        try:
            level = int(tags.get("admin_level") or 0)
        except ValueError:
            continue
        if not name or not (MIN_ADMIN_LEVEL <= level <= MAX_ADMIN_LEVEL):
            continue
        polys = []
        try:
            for outer in area.outer_rings():
                ring = [[round(n.lon, 6), round(n.lat, 6)] for n in outer]
                if len(ring) < 4:
                    continue
                poly = [ring]
                for inner in area.inner_rings(outer):
                    hole = [[round(n.lon, 6), round(n.lat, 6)] for n in inner]
                    if len(hole) >= 4:
                        poly.append(hole)
                polys.append(poly)
        except osmium.InvalidLocationError:
            continue
        if not polys:
            continue
        geom = (
            {"type": "Polygon", "coordinates": polys[0]}
            if len(polys) == 1
            else {"type": "MultiPolygon", "coordinates": polys}
        )
        bb = _bbox(geom)
        if bb[2] - bb[0] > MAX_SPAN_DEG or bb[3] - bb[1] > MAX_SPAN_DEG:
            continue
        clon, clat = _label_point(geom)
        rows.append(
            (
                "way" if area.from_way() else "relation",
                area.orig_id(),
                name,
                level,
                *bb,
                clon,
                clat,
                json.dumps(geom, separators=(",", ":")),
                extract_id,
            )
        )
    conn = _connect()
    try:
        conn.execute("DELETE FROM areas WHERE extract_id = ?", (extract_id,))
        conn.executemany(
            "INSERT OR REPLACE INTO areas VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows
        )
        conn.execute(
            "INSERT OR REPLACE INTO extracts VALUES (?,?,?)",
            (extract_id, time.time(), len(rows)),
        )
        conn.commit()
    finally:
        conn.close()
    progress(f"[admin_areas] {extract_id}: {len(rows)} areas in {time.monotonic() - t0:.0f}s")
    return len(rows)


# --- lookups ----------------------------------------------------------------


def _row_to_area(row: sqlite3.Row, *, with_geom: bool = True) -> dict:
    out = {
        "osm_type": row["osm_type"],
        "osm_id": row["osm_id"],
        "name": row["name"],
        "admin_level": row["admin_level"],
        "bbox": [row["minlon"], row["minlat"], row["maxlon"], row["maxlat"]],
        "lon": row["clon"],
        "lat": row["clat"],
    }
    if with_geom:
        out["boundary"] = json.loads(row["geojson"])
    return out


def find_city(lat: float, lon: float, name: str | None = None) -> dict | None:
    """Best admin polygon for a city point: exact name first, then municipality level (8)."""
    if not DB_PATH.exists():
        return None
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT * FROM areas
            WHERE minlon <= ? AND maxlon >= ? AND minlat <= ? AND maxlat >= ?
              AND admin_level <= 8
            """,
            (lon, lon, lat, lat),
        ).fetchall()
    finally:
        conn.close()
    name_l = (name or "").strip().casefold()
    scored = []
    for row in rows:
        tname = row["name"].casefold()
        name_hit = 0
        if name_l:
            if name_l == tname:
                name_hit = -30
            elif name_l in tname or tname in name_l:
                name_hit = -10
        level = row["admin_level"]
        level_pref = 0 if (name_hit <= -30 and level <= 6) else abs(level - 8)
        area = (row["maxlon"] - row["minlon"]) * (row["maxlat"] - row["minlat"])
        scored.append((name_hit, level_pref, area, row))
    scored.sort(key=lambda x: (x[0], x[1], x[2]))
    for *_, row in scored:
        geom = json.loads(row["geojson"])
        if point_in_geom(lon, lat, geom):
            return _row_to_area(row, with_geom=True)
    return None


def find_covering_district(city: dict, lat: float, lon: float) -> dict | None:
    """District (or deeper part) whose polygon contains the point, if any."""
    _level, districts = find_districts(city)
    if not districts:
        return None
    ids = [int(d["osm_id"]) for d in districts]
    if not ids or not DB_PATH.exists():
        return None
    conn = _connect()
    try:
        qmarks = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT osm_id, name, admin_level, clon, clat, minlon, minlat, maxlon, maxlat, geojson "
            f"FROM areas WHERE osm_type = 'relation' AND osm_id IN ({qmarks})",
            ids,
        ).fetchall()
    finally:
        conn.close()
    by_id = {int(r["osm_id"]): r for r in rows}
    # Prefer smaller (deeper) areas first if multiple contain the point
    ranked = sorted(
        districts,
        key=lambda d: (
            -int(d.get("admin_level") or 0),
            (d["bbox"][2] - d["bbox"][0]) * (d["bbox"][3] - d["bbox"][1])
            if d.get("bbox")
            else 9e9,
        ),
    )
    for d in ranked:
        row = by_id.get(int(d["osm_id"]))
        if not row:
            continue
        geom = json.loads(row["geojson"])
        if point_in_geom(lon, lat, geom):
            out = dict(d)
            out["boundary"] = geom
            return out
    return None


def _clean_district_name(name: str) -> str:
    n = (name or "").strip()
    for prefix in ("Gemarkung ", "Stadtbezirk "):
        if n.casefold().startswith(prefix.casefold()) and not re.match(
            r"(?i)^Stadtbezirk\s+\d", n
        ):
            # Keep "Stadtbezirk 1"; strip "Gemarkung Ronsdorf" → "Ronsdorf"
            if prefix.lower().startswith("gemarkung"):
                n = n[len(prefix) :].strip()
    if n.casefold().startswith("gemarkung "):
        n = n[10:].strip()
    return n or name


def find_districts(city: dict, max_count: int = 40) -> tuple[int | None, list[dict]]:
    """
    Named admin areas below the city.

    Prefer the shallowest deeper admin_level with ≥2 parts (e.g. Stadtbezirke).
    If those leave a clear hole in the city, also pull deeper areas that sit in
    the gap (e.g. Wuppertal's Ronsdorf tagged as Gemarkung / admin_level 10).
    """
    minlon, minlat, maxlon, maxlat = city["bbox"]
    parent_area = (maxlon - minlon) * (maxlat - minlat)
    city_km2 = geom_area_km2(city.get("boundary")) or 0.0
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT * FROM areas
            WHERE admin_level > ? AND clon BETWEEN ? AND ? AND clat BETWEEN ? AND ?
            ORDER BY admin_level, name
            """,
            (city["admin_level"], minlon, maxlon, minlat, maxlat),
        ).fetchall()
    finally:
        conn.close()
    parent_geom = city["boundary"]
    by_level: dict[int, list[dict]] = {}
    for row in rows:
        area = (row["maxlon"] - row["minlon"]) * (row["maxlat"] - row["minlat"])
        if parent_area > 0 and area / parent_area > 0.85:
            continue
        if not point_in_geom(row["clon"], row["clat"], parent_geom):
            continue
        item = _row_to_area(row, with_geom=True)
        item["name"] = _clean_district_name(item["name"])
        by_level.setdefault(row["admin_level"], []).append(item)

    primary_level = None
    primary: list[dict] = []
    for level in sorted(by_level):
        parts = by_level[level]
        if len(parts) >= 2:
            primary_level = level
            primary = parts
            break
    if not primary:
        return None, []

    # Gap-fill from the next deeper level when coverage is incomplete
    sum_km2 = sum(geom_area_km2(p.get("boundary")) or 0.0 for p in primary)
    if city_km2 > 0 and sum_km2 / city_km2 < 0.92:
        deeper = by_level.get((primary_level or 0) + 1) or []
        for cand in deeper:
            clon, clat = cand["lon"], cand["lat"]
            covered = any(
                point_in_geom(clon, clat, p.get("boundary") or {})
                for p in primary
                if p.get("boundary")
            )
            if covered:
                continue
            # Avoid near-duplicates by name
            if any(p["name"].casefold() == cand["name"].casefold() for p in primary):
                continue
            primary.append(cand)

    # Drop full geometries from the list payload (loaded again on select)
    out = []
    for p in primary:
        out.append({k: v for k, v in p.items() if k != "boundary"})
    out.sort(key=_natural_key)
    return primary_level, out[:max_count]


def _natural_key(area: dict) -> list:
    """'Stadtbezirk 2' before 'Stadtbezirk 10'."""
    return [int(t) if t.isdigit() else t.casefold() for t in re.split(r"(\d+)", area["name"])]


def get_area(osm_id: int, osm_type: str = "relation") -> dict | None:
    if not DB_PATH.exists():
        return None
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM areas WHERE osm_id = ? ORDER BY osm_type = ? DESC LIMIT 1",
            (int(osm_id), osm_type),
        ).fetchone()
    finally:
        conn.close()
    return _row_to_area(row) if row else None
