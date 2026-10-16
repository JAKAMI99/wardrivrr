"""
Per-level OSM address packs for offline reverse geocoding.

Built when a level is generated (clipped to the level bbox/boundary) so we do
not store a country-wide address DB. Lookup prefers the nearest addr:* point
within a short radius; street/housenumber come from OpenStreetMap tags.
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable

from paths import ROOT, USERS, level_dir

META_NAME = "addresses.sqlite"
REGISTRY = ROOT / "data" / "geocode" / "address_packs.json"

# Prefer house-level hits inside this distance; then expand.
_NEAR_M = 90.0
_MAX_M = 180.0


def address_db_path(user_id: int, level_id: int) -> Path:
    return level_dir(user_id, level_id) / META_NAME


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _format_display(
    street: str | None,
    housenumber: str | None,
    postcode: str | None,
    city: str | None,
) -> str:
    left = " ".join(p for p in (street, housenumber) if p).strip()
    right = " ".join(p for p in (postcode, city) if p).strip()
    if left and right:
        return f"{left}, {right}"
    return left or right or ""


def _tags_addr(tags) -> dict[str, str | None] | None:
    hn = (tags.get("addr:housenumber") or "").strip() or None
    if not hn:
        return None
    street = (tags.get("addr:street") or "").strip() or None
    postcode = (tags.get("addr:postcode") or "").strip() or None
    city = (
        (tags.get("addr:city") or "").strip()
        or (tags.get("addr:town") or "").strip()
        or (tags.get("addr:place") or "").strip()
        or None
    )
    return {
        "housenumber": hn,
        "street": street,
        "postcode": postcode,
        "city": city,
    }


def _in_bbox(lon: float, lat: float, bb: list[float]) -> bool:
    return bb[0] <= lon <= bb[2] and bb[1] <= lat <= bb[3]


def extract_addresses_from_pbf(
    pbf_path: Path,
    *,
    bbox: list[float] | None = None,
    boundary: dict | None = None,
    progress: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """
    Pull addr:housenumber nodes/ways from a PBF, limited to bbox/boundary.
    Ways use the average of node coordinates as the point.
    """
    import osmium

    pad = 0.005
    bb = None
    if bbox and len(bbox) == 4:
        bb = [
            float(bbox[0]) - pad,
            float(bbox[1]) - pad,
            float(bbox[2]) + pad,
            float(bbox[3]) + pad,
        ]

    # Lazy import — levels pulls in psycopg2; only needed for polygon clip
    _pin = None
    if boundary:

        def _pin(lon: float, lat: float, geom: dict | None = boundary) -> bool:
            from levels import point_in_boundary

            return point_in_boundary(lon, lat, geom)

    rows: list[dict[str, Any]] = []

    class Handler(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.n = 0

        def _accept(self, lon: float, lat: float) -> bool:
            if bb and not _in_bbox(lon, lat, bb):
                return False
            if _pin is not None and not _pin(lon, lat):
                return False
            return True

        def _add(self, lon: float, lat: float, tags) -> None:
            addr = _tags_addr(tags)
            if not addr:
                return
            if not self._accept(lon, lat):
                return
            display = _format_display(
                addr["street"], addr["housenumber"], addr["postcode"], addr["city"]
            )
            rows.append(
                {
                    "lat": lat,
                    "lon": lon,
                    "street": addr["street"],
                    "housenumber": addr["housenumber"],
                    "postcode": addr["postcode"],
                    "city": addr["city"],
                    "display": display,
                }
            )
            self.n += 1
            if progress and self.n % 5000 == 0:
                progress(f"Found {self.n:,} addresses…")

        def node(self, n):
            if "addr:housenumber" not in n.tags:
                return
            if not n.location.valid():
                return
            self._add(n.location.lon, n.location.lat, n.tags)

        def way(self, w):
            if "addr:housenumber" not in w.tags:
                return
            if len(w.nodes) < 1:
                return
            lons: list[float] = []
            lats: list[float] = []
            try:
                for nd in w.nodes:
                    if not nd.location.valid():
                        return
                    lons.append(nd.location.lon)
                    lats.append(nd.location.lat)
            except osmium.InvalidLocationError:
                return
            if not lons:
                return
            self._add(sum(lons) / len(lons), sum(lats) / len(lats), w.tags)

    if progress:
        progress(f"Scanning addresses in {pbf_path.name}…")
    h = Handler()
    h.apply_file(str(pbf_path), locations=True)
    if progress:
        progress(f"Extracted {len(rows):,} addresses")
    return rows


def write_address_db(
    dest: Path,
    rows: list[dict[str, Any]],
    *,
    bbox: list[float] | None = None,
    meta: dict | None = None,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    conn = sqlite3.connect(str(dest))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE addresses (
              id INTEGER PRIMARY KEY,
              lat REAL NOT NULL,
              lon REAL NOT NULL,
              street TEXT,
              housenumber TEXT,
              postcode TEXT,
              city TEXT,
              display TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE VIRTUAL TABLE addresses_rtree USING rtree(
              id, min_lon, max_lon, min_lat, max_lat
            )
            """
        )
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        meta_out = dict(meta or {})
        if bbox and len(bbox) == 4:
            meta_out.update(
                {
                    "bbox_w": str(bbox[0]),
                    "bbox_s": str(bbox[1]),
                    "bbox_e": str(bbox[2]),
                    "bbox_n": str(bbox[3]),
                }
            )
        meta_out["count"] = str(len(rows))
        meta_out["built_at"] = str(int(time.time()))
        conn.executemany(
            "INSERT INTO meta(key, value) VALUES (?, ?)",
            list(meta_out.items()),
        )
        batch = []
        for i, r in enumerate(rows, start=1):
            lat, lon = float(r["lat"]), float(r["lon"])
            batch.append(
                (
                    i,
                    lat,
                    lon,
                    r.get("street"),
                    r.get("housenumber"),
                    r.get("postcode"),
                    r.get("city"),
                    r.get("display")
                    or _format_display(
                        r.get("street"),
                        r.get("housenumber"),
                        r.get("postcode"),
                        r.get("city"),
                    ),
                )
            )
            if len(batch) >= 2000:
                _flush_batch(conn, batch)
                batch = []
        if batch:
            _flush_batch(conn, batch)
        conn.commit()
    finally:
        conn.close()
    return dest


def _flush_batch(conn: sqlite3.Connection, batch: list[tuple]) -> None:
    conn.executemany(
        """
        INSERT INTO addresses(id, lat, lon, street, housenumber, postcode, city, display)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        batch,
    )
    conn.executemany(
        """
        INSERT INTO addresses_rtree(id, min_lon, max_lon, min_lat, max_lat)
        VALUES (?, ?, ?, ?, ?)
        """,
        [(b[0], b[2], b[2], b[1], b[1]) for b in batch],
    )


def _load_registry() -> list[dict]:
    if not REGISTRY.exists():
        return []
    try:
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_registry(entries: list[dict]) -> None:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def register_pack(
    user_id: int,
    level_id: int,
    path: Path,
    *,
    bbox: list[float] | None,
    count: int,
) -> None:
    entries = [
        e
        for e in _load_registry()
        if not (e.get("user_id") == user_id and e.get("level_id") == level_id)
    ]
    entries.append(
        {
            "user_id": user_id,
            "level_id": level_id,
            "path": str(path.resolve()),
            "bbox": bbox,
            "count": count,
            "built_at": int(time.time()),
        }
    )
    _save_registry(entries)


def discover_packs() -> list[dict]:
    """Registry first; also pick up any on-disk packs missing from registry."""
    by_key: dict[tuple[int, int], dict] = {}
    for e in _load_registry():
        try:
            key = (int(e["user_id"]), int(e["level_id"]))
            p = Path(e["path"])
            if p.exists():
                by_key[key] = e
        except Exception:
            continue
    if USERS.exists():
        for user_path in USERS.iterdir():
            if not user_path.is_dir() or not user_path.name.isdigit():
                continue
            levels_root = user_path / "levels"
            if not levels_root.is_dir():
                continue
            for lp in levels_root.iterdir():
                if not lp.is_dir() or not lp.name.isdigit():
                    continue
                db = lp / META_NAME
                if not db.exists():
                    continue
                key = (int(user_path.name), int(lp.name))
                if key in by_key:
                    continue
                bbox = _meta_bbox(db)
                by_key[key] = {
                    "user_id": key[0],
                    "level_id": key[1],
                    "path": str(db.resolve()),
                    "bbox": bbox,
                    "count": None,
                }
    return list(by_key.values())


def _meta_bbox(db_path: Path) -> list[float] | None:
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            rows = {
                r[0]: r[1]
                for r in conn.execute("SELECT key, value FROM meta").fetchall()
            }
            keys = ("bbox_w", "bbox_s", "bbox_e", "bbox_n")
            if all(k in rows for k in keys):
                return [float(rows[k]) for k in keys]
        finally:
            conn.close()
    except Exception:
        return None
    return None


def build_level_address_pack(
    user_id: int,
    level_id: int,
    pbf_path: Path,
    *,
    bbox: list[float] | None = None,
    boundary: dict | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict:
    """Extract + write addresses.sqlite for a level; register for reverse lookup."""
    if not pbf_path.exists():
        raise FileNotFoundError(pbf_path)
    rows = extract_addresses_from_pbf(
        pbf_path, bbox=bbox, boundary=boundary, progress=progress
    )
    dest = address_db_path(user_id, level_id)
    write_address_db(
        dest,
        rows,
        bbox=bbox,
        meta={"user_id": str(user_id), "level_id": str(level_id)},
    )
    register_pack(user_id, level_id, dest, bbox=bbox, count=len(rows))
    return {"path": str(dest), "count": len(rows), "bbox": bbox}


def nearest_address(
    lat: float,
    lon: float,
    *,
    max_m: float = _MAX_M,
) -> dict | None:
    """Nearest OSM address from any level pack whose bbox covers the point."""
    packs = discover_packs()
    if not packs:
        return None

    best: dict | None = None
    best_d = 1e18
    # ~degrees for search window
    pad0 = max_m / 111_320.0

    for pack in packs:
        bb = pack.get("bbox")
        if bb and len(bb) == 4:
            # Allow a small margin outside bbox for edge houses
            if not (
                bb[0] - 0.01 <= lon <= bb[2] + 0.01
                and bb[1] - 0.01 <= lat <= bb[3] + 0.01
            ):
                continue
        path = Path(pack["path"])
        if not path.exists():
            continue
        try:
            hit = _nearest_in_db(path, lat, lon, pad_deg=pad0, max_m=max_m)
        except Exception:
            continue
        if hit and hit["distance_m"] < best_d:
            best_d = hit["distance_m"]
            best = hit
            if best_d <= _NEAR_M:
                # good enough — still finish other packs only if closer needed
                pass
    return best


def _nearest_in_db(
    path: Path,
    lat: float,
    lon: float,
    *,
    pad_deg: float,
    max_m: float,
) -> dict | None:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        best = None
        best_d = 1e18
        for pad in (pad_deg, pad_deg * 2, pad_deg * 4):
            rows = conn.execute(
                """
                SELECT a.id, a.lat, a.lon, a.street, a.housenumber,
                       a.postcode, a.city, a.display
                FROM addresses_rtree r
                JOIN addresses a ON a.id = r.id
                WHERE r.min_lon BETWEEN ? AND ?
                  AND r.min_lat BETWEEN ? AND ?
                """,
                (lon - pad, lon + pad, lat - pad, lat + pad),
            ).fetchall()
            for row in rows:
                d = _haversine_m(lat, lon, float(row["lat"]), float(row["lon"]))
                if d < best_d:
                    best_d = d
                    best = row
            if best is not None and best_d <= _NEAR_M:
                break
        if best is None or best_d > max_m:
            return None
        return {
            "street": best["street"],
            "housenumber": best["housenumber"],
            "postcode": best["postcode"],
            "city": best["city"],
            "display": best["display"]
            or _format_display(
                best["street"], best["housenumber"], best["postcode"], best["city"]
            ),
            "lat": float(best["lat"]),
            "lon": float(best["lon"]),
            "distance_m": best_d,
            "source": "level_osm_addresses",
        }
    finally:
        conn.close()
