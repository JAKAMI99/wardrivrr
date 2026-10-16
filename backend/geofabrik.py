from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any

INDEX_URL = "https://download.geofabrik.de/index-v1.json"
CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "geofabrik-index-v1.json"


def _download_index(force: bool = False) -> dict:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if CACHE_PATH.exists() and not force:
        age_ok = True
        try:
            import time

            age_ok = (time.time() - CACHE_PATH.stat().st_mtime) < 7 * 86400
        except OSError:
            age_ok = False
        if age_ok:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    with urllib.request.urlopen(INDEX_URL, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    CACHE_PATH.write_text(json.dumps(data), encoding="utf-8")
    return data


@lru_cache(maxsize=1)
def load_features() -> tuple[dict, ...]:
    data = _download_index()
    feats = data.get("features") or []
    return tuple(feats)


def refresh_index() -> int:
    load_features.cache_clear()
    _download_index(force=True)
    return len(load_features())


def ensure_index() -> int:
    """Ensure Geofabrik index-v1.json is cached locally (download on first start)."""
    load_features.cache_clear()
    feats = load_features()
    print(f"[geofabrik] index ready ({len(feats)} extracts)")
    return len(feats)


def _props(feat: dict) -> dict:
    return feat.get("properties") or {}


def _name(feat: dict) -> str:
    p = _props(feat)
    return p.get("name") or p.get("id") or ""


def _id(feat: dict) -> str:
    return str(_props(feat).get("id") or "")


def _urls(feat: dict) -> dict:
    return _props(feat).get("urls") or {}


def _bbox_from_geometry(feat: dict) -> list[float] | None:
    geom = feat.get("geometry") or {}
    gtype = geom.get("type")
    coords = geom.get("coordinates")
    if not coords:
        bb = feat.get("bbox")
        if bb and len(bb) == 4:
            return [float(x) for x in bb]
        return None

    def walk(c, box):
        if isinstance(c, (list, tuple)) and c and isinstance(c[0], (int, float)):
            lon, lat = float(c[0]), float(c[1])
            box[0] = min(box[0], lon)
            box[1] = min(box[1], lat)
            box[2] = max(box[2], lon)
            box[3] = max(box[3], lat)
        elif isinstance(c, (list, tuple)):
            for item in c:
                walk(item, box)

    box = [180.0, 90.0, -180.0, -90.0]
    walk(coords, box)
    if box[0] > box[2]:
        return None
    return box


def _point_in_bbox(lon: float, lat: float, bbox: list[float]) -> bool:
    return bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]


def _point_in_ring(lon: float, lat: float, ring: list) -> bool:
    # Ray casting
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = float(ring[i][0]), float(ring[i][1])
        xj, yj = float(ring[j][0]), float(ring[j][1])
        if ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-15) + xi
        ):
            inside = not inside
        j = i
    return inside


def _point_in_feature(lon: float, lat: float, feat: dict) -> bool:
    geom = feat.get("geometry") or {}
    gtype = geom.get("type")
    coords = geom.get("coordinates")
    if not coords:
        bbox = _bbox_from_geometry(feat)
        return bool(bbox and _point_in_bbox(lon, lat, bbox))
    if gtype == "Polygon":
        return _point_in_ring(lon, lat, coords[0])
    if gtype == "MultiPolygon":
        for poly in coords:
            if poly and _point_in_ring(lon, lat, poly[0]):
                return True
    bbox = _bbox_from_geometry(feat)
    return bool(bbox and _point_in_bbox(lon, lat, bbox))


def _size_bytes(feat: dict) -> int | None:
    p = _props(feat)
    for key in ("pbf_file_size", "osm.pbf.size", "size"):
        if key in p and p[key] is not None:
            try:
                return int(p[key])
            except (TypeError, ValueError):
                pass
    return None


def feature_summary(feat: dict, extra: dict | None = None) -> dict[str, Any]:
    urls = _urls(feat)
    pbf = urls.get("pbf") or urls.get("osm.pbf")
    out = {
        "id": _id(feat),
        "name": _name(feat),
        "parent": _props(feat).get("parent"),
        "pbf_url": pbf,
        "bbox": _bbox_from_geometry(feat),
        "size_bytes": _size_bytes(feat),
    }
    if extra:
        out.update(extra)
    return out


def local_city_lookup(query: str) -> dict | None:
    """Resolve a place name via the offline cities DB (no Nominatim)."""
    try:
        from cities_db import db_available, search_cities

        if not db_available():
            return None
        hits = search_cities(query, limit=1, min_population=5_000)
        if not hits:
            return None
        h = hits[0]
        return {
            "display_name": h.get("display_name") or h.get("label"),
            "lon": h["lon"],
            "lat": h["lat"],
            "place_bbox": h.get("bbox"),
        }
    except Exception:
        return None


def covering_extracts(
    lon: float,
    lat: float,
    limit: int = 8,
    place_bbox: list[float] | None = None,
) -> list[dict]:
    """Smallest Geofabrik extracts whose polygon contains the point.

    When place_bbox is set, require the bbox center (and prefer extracts that
    contain most corners) to reduce border false-positives between adjacent regions.
    """
    probes = [(lon, lat)]
    if place_bbox and len(place_bbox) == 4:
        minlon, minlat, maxlon, maxlat = place_bbox
        cx, cy = (minlon + maxlon) / 2, (minlat + maxlat) / 2
        probes = [
            (cx, cy),
            (minlon, minlat),
            (minlon, maxlat),
            (maxlon, minlat),
            (maxlon, maxlat),
        ]
    hits = []
    for feat in load_features():
        if not _urls(feat).get("pbf") and not _urls(feat).get("osm.pbf"):
            continue
        contained = sum(1 for plon, plat in probes if _point_in_feature(plon, plat, feat))
        # Center (first probe) must be inside; need majority of probes for place_bbox
        if not _point_in_feature(probes[0][0], probes[0][1], feat):
            continue
        if place_bbox and contained < 3:
            continue
        summary = feature_summary(feat)
        depth = summary["id"].count("/") + summary["id"].count("-")
        area = None
        if summary["bbox"]:
            b = summary["bbox"]
            area = abs(b[2] - b[0]) * abs(b[3] - b[1])
        hits.append((area if area is not None else 1e9, -contained, -depth, summary))
    hits.sort(key=lambda x: (x[0], x[1], x[2]))
    return [h[3] for h in hits[:limit]]


def search_places(query: str, limit: int = 15) -> list[dict]:
    q = (query or "").strip()
    if not q:
        return []
    results: list[dict] = []
    seen: set[str] = set()

    # 1) Direct Geofabrik name/id match
    tokens = [t for t in re.split(r"\s+", q.lower()) if t]
    scored: list[tuple[int, dict]] = []
    for feat in load_features():
        name = _name(feat).lower()
        fid = _id(feat).lower()
        hay = f"{name} {fid}"
        if not all(t in hay for t in tokens):
            continue
        score = 0
        if name == q.lower() or fid == q.lower():
            score += 100
        if name.startswith(q.lower()):
            score += 50
        score += min(20, fid.count("/") * 3)
        summary = feature_summary(feat)
        if not summary.get("pbf_url"):
            continue
        scored.append((score, summary))
    scored.sort(key=lambda x: (-x[0], len(x[1]["id"])))
    for _, s in scored:
        if s["id"] not in seen:
            seen.add(s["id"])
            results.append(s)

    # 2) Place name → local cities DB → covering extracts (e.g. Berlin → Berlin / Brandenburg)
    place = local_city_lookup(q)
    if place:
        covers = covering_extracts(
            place["lon"],
            place["lat"],
            limit=max(limit, 12),
            place_bbox=place.get("place_bbox"),
        )
        display = (place.get("display_name") or "").lower()

        # Prefer finest (smallest) covering extract; soft-boost address token hits
        def place_rank(s: dict) -> tuple:
            name = (s.get("name") or "").lower()
            fid = (s.get("id") or "").lower()
            soft = 0
            for token in re.split(r"[^a-z0-9]+", fid + " " + name):
                if len(token) >= 6 and token in display.replace("ü", "ue").replace("ä", "ae"):
                    soft -= 1
            depth = fid.count("-") + fid.count("/")
            area = 1e9
            if s.get("bbox"):
                b = s["bbox"]
                area = abs(b[2] - b[0]) * abs(b[3] - b[1])
            # Primary: smaller area (finer extract). Soft address match breaks ties.
            return (area, soft, -depth)

        covers.sort(key=place_rank)
        for s in covers:
            if s["id"] not in seen:
                seen.add(s["id"])
                s = dict(s)
                s["matched_place"] = place.get("display_name")
                s["place_bbox"] = place.get("place_bbox")
                results.append(s)

    return results[:limit]


def resolve_feature(geofabrik_id: str) -> dict | None:
    gid = (geofabrik_id or "").strip()
    for feat in load_features():
        if _id(feat) == gid:
            return feature_summary(feat)
    return None


def probe_pbf_size(url: str) -> int | None:
    """Best-effort Content-Length via HEAD (or Range GET)."""
    if not url:
        return None
    try:
        req = urllib.request.Request(
            url, method="HEAD", headers={"User-Agent": "wardrivrr/1.0"}
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            cl = resp.headers.get("Content-Length")
            if cl:
                return int(cl)
    except Exception:
        pass
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "wardrivrr/1.0", "Range": "bytes=0-0"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            cr = resp.headers.get("Content-Range")  # bytes 0-0/12345
            if cr and "/" in cr:
                total = cr.split("/")[-1]
                if total.isdigit():
                    return int(total)
            cl = resp.headers.get("Content-Length")
            if cl and int(cl) > 1:
                return int(cl)
    except Exception:
        pass
    return None


def download_pbf(url: str, dest: Path, progress_cb=None) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "wardrivrr/1.0"})
    with urllib.request.urlopen(req, timeout=600) as resp, open(tmp, "wb") as out:
        total = resp.headers.get("Content-Length")
        total_n = int(total) if total else None
        done = 0
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress_cb:
                frac = (done / total_n) if total_n else min(0.95, done / (50 * 1024 * 1024))
                progress_cb(min(1.0, frac), done, total_n)
    tmp.replace(dest)
    return dest.stat().st_size


def _bbox_overlap_ratio(a: list[float], b: list[float]) -> float:
    """Intersection-over-place ratio for [w,s,e,n] boxes."""
    aw, as_, ae, an = a
    bw, bs, be, bn = b
    iw = max(0.0, min(ae, be) - max(aw, bw))
    ih = max(0.0, min(an, bn) - max(as_, bs))
    inter = iw * ih
    place = max(1e-12, (ae - aw) * (an - as_))
    return inter / place


def _bbox_interior_score(lon: float, lat: float, bbox: list[float]) -> float:
    """How central a point is inside a bbox (0 at edge, ~0.5 at center)."""
    w, s, e, n = bbox
    if not (w <= lon <= e and s <= lat <= n):
        return -1.0
    return min(lon - w, e - lon, lat - s, n - lat) / max(e - w, n - s, 1e-9)


def _parent_map() -> dict[str, str]:
    """id → parent id from the Geofabrik index."""
    out: dict[str, str] = {}
    for feat in load_features():
        fid = _id(feat)
        parent = _props(feat).get("parent")
        if fid and parent:
            out[fid] = str(parent)
    return out


def _ancestor_ids(fid: str, parents: dict[str, str]) -> list[str]:
    chain = [fid]
    seen = {fid}
    cur = fid
    while cur in parents:
        cur = parents[cur]
        if cur in seen:
            break
        seen.add(cur)
        chain.append(cur)
    return chain


def resolve_place_extract(
    lat: float,
    lon: float,
    place_bbox: list[float] | None = None,
    *,
    country_code: str | None = None,
    country_name: str | None = None,
    place_name: str | None = None,
) -> dict | None:
    """Pick the finest Geofabrik extract covering a place (hidden from end users).

    Uses the city center for containment (approximate urban bboxes often spill into
    neighbouring extracts). Prefers extracts under the matching country in the
    Geofabrik parent chain, then the smallest (finest) such extract.
    """
    # Small probe box around the city center (not the large urban estimate) so
    # neighbouring Geofabrik polygons that only graze the point lose the majority vote.
    pad = 0.05
    tight_bbox = [lon - pad, lat - pad, lon + pad, lat + pad]
    covers = covering_extracts(lon, lat, limit=32, place_bbox=tight_bbox)
    if not covers:
        covers = covering_extracts(lon, lat, limit=32, place_bbox=None)
    if not covers:
        return None

    cc = (country_code or "").strip().lower()
    cname = (country_name or "").strip().lower()
    ctokens = [t for t in re.split(r"[^a-z0-9]+", cname) if len(t) >= 4]
    place_tokens = {
        t
        for t in re.split(r"[^a-z0-9]+", (place_name or "").strip().lower())
        if len(t) >= 4 and t not in {"city", "town", "saint", "north", "south", "east", "west"}
    }
    aliases = {
        "us": ("usa", "united-states", "us"),
        "gb": ("great-britain", "britain", "england", "scotland", "wales"),
        "ru": ("russia",),
        "kr": ("south-korea", "korea"),
        "cz": ("czech-republic", "czech"),
        "ae": ("gcc-states",),
        "za": ("south-africa", "south-africa-and-lesotho"),
    }
    country_keys = set(ctokens)
    country_keys.update(aliases.get(cc, ()))
    if cc:
        country_keys.add(cc)

    parents = _parent_map()
    continent_ids = {
        "africa",
        "asia",
        "europe",
        "south-america",
        "north-america",
        "australia-oceania",
        "central-america",
        "antarctica",
    }

    def under_country(fid: str, name: str) -> bool:
        if not country_keys:
            return True
        chain = _ancestor_ids(fid, parents)
        # Tokenize so ISO codes like "de" do not match inside "dach"
        parts = re.split(r"[^a-z0-9]+", " ".join(chain + [name.lower()]))
        tokens = {p for p in parts if p}
        # Also allow path segments (us/new-york → us, new, york)
        for part in list(tokens):
            if "/" in part:
                tokens.update(part.split("/"))
        return any(key in tokens for key in country_keys)

    # Drop ancestors when a finer child also covers the city (keep leaf extracts)
    cover_ids = {c["id"] for c in covers if c.get("id")}
    leaves = []
    for feat in covers:
        fid = feat.get("id") or ""
        is_parent_of_other = any(
            fid in _ancestor_ids(other, parents)[1:]
            for other in cover_ids
            if other != fid
        )
        if not is_parent_of_other:
            leaves.append(feat)
    if leaves:
        covers = leaves

    def score(feat: dict) -> tuple:
        fid = (feat.get("id") or "").lower()
        name = (feat.get("name") or "").lower()
        depth = len(_ancestor_ids(fid, parents))
        area = 1e9
        if feat.get("bbox"):
            b = feat["bbox"]
            area = abs(b[2] - b[0]) * abs(b[3] - b[1])
        matched = under_country(fid, name)
        bucket = 0 if matched else (2 if fid in continent_ids else 1)
        interior = -1.0
        if feat.get("bbox"):
            interior = _bbox_interior_score(lon, lat, feat["bbox"])
        size_tier = 0 if area < 4.0 else (1 if area < 40.0 else 2)
        # Soft name match (New York → us/new-york, Tokyo → … rarely in id)
        name_hit = 0
        if place_tokens:
            hay_parts = set(re.split(r"[^a-z0-9]+", f"{fid} {name}"))
            if place_tokens & hay_parts:
                name_hit = -1
        return (bucket, name_hit, size_tier, -interior, area, -depth)

    covers.sort(key=score)
    best = dict(covers[0])
    size = best.get("size_bytes") or probe_pbf_size(best.get("pbf_url") or "")
    best["size_bytes"] = size
    return best
