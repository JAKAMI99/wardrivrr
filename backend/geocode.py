from __future__ import annotations

import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

DISK_CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "geocode_reverse_cache.json"

_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 6 * 3600
_DISK: dict[str, Any] | None = None
_DISK_DIRTY = False
_DISK_LOCK = threading.Lock()


def _get_cached(key: str):
    hit = _CACHE.get(key)
    if not hit:
        return None
    exp, val = hit
    if time.time() > exp:
        _CACHE.pop(key, None)
        return None
    return val


def _set_cached(key: str, val: Any) -> None:
    _CACHE[key] = (time.time() + _CACHE_TTL, val)


def _hit_from_city(h: dict) -> dict:
    bbox = h.get("bbox")
    return {
        "display_name": h.get("display_name") or h.get("label"),
        "lat": float(h["lat"]),
        "lon": float(h["lon"]),
        "bbox": bbox,
        "type": "city",
        "class": "place",
        "country_code": h.get("country_code"),
        "source": "local_cities_db",
    }


def geocode_place(
    place: str,
    *,
    country: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """Resolve a place name via the local worldwide cities database."""
    place = (place or "").strip()
    if not place:
        return []
    q = place
    if country:
        q = f"{place} {country}"
    try:
        from cities_db import db_available, ensure_cities_db, search_cities

        if not db_available():
            ensure_cities_db()
        hits = search_cities(q, limit=limit, min_population=1_000)
        if country:
            cc = country.strip().upper()
            filtered = [h for h in hits if (h.get("country_code") or "").upper() == cc]
            if filtered:
                hits = filtered
        return [_hit_from_city(h) for h in hits]
    except Exception:
        return []


def geocode_postalcode(
    postalcode: str,
    *,
    country: str | None = "de",
    limit: int = 5,
) -> list[dict]:
    """Resolve a ZIP / postal code via local GeoNames postal DB."""
    postalcode = (postalcode or "").strip()
    if not postalcode:
        return []
    try:
        from local_geocode import ensure_postal_db, postal_db_available, search_postal

        if not postal_db_available():
            ensure_postal_db()
        return search_postal(postalcode, country=country, limit=limit)
    except Exception:
        return []


def reverse_geocode(lat: float, lon: float, zoom: int = 16) -> dict | None:
    """Point → address / place label (fully local)."""
    _ = zoom
    try:
        from local_geocode import reverse_local

        return reverse_local(float(lat), float(lon))
    except Exception:
        return None


def _load_disk() -> dict[str, Any]:
    global _DISK
    if _DISK is not None:
        return _DISK
    if DISK_CACHE_PATH.exists():
        try:
            import json

            _DISK = json.loads(DISK_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            _DISK = {}
    else:
        _DISK = {}
    return _DISK


def _save_disk() -> None:
    global _DISK_DIRTY
    if not _DISK_DIRTY or _DISK is None:
        return
    import json

    DISK_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DISK_CACHE_PATH.write_text(json.dumps(_DISK), encoding="utf-8")
    _DISK_DIRTY = False


def reverse_geocode_cached(lat: float, lon: float, zoom: int = 16) -> dict | None:
    """Reverse geocode with grid + disk cache (~11 m cells at 4 decimal places)."""
    global _DISK_DIRTY
    # v3: never permanently cache misses (address packs arrive after first miss).
    key = f"v3:{round(float(lat), 4)}:{round(float(lon), 4)}:{zoom}"
    cached = _CACHE.get(key)
    if cached:
        exp, val = cached
        if time.time() <= exp:
            return val
        _CACHE.pop(key, None)
    with _DISK_LOCK:
        disk = _load_disk()
        if key in disk and disk[key] is not None:
            hit = disk[key]
            _set_cached(key, hit)
            return hit
        # Drop legacy null miss entries so later packs can fill addresses.
        if key in disk and disk[key] is None:
            disk.pop(key, None)
            _DISK_DIRTY = True
    hit = reverse_geocode(lat, lon, zoom=zoom)
    if hit is None:
        # Short negative cache only — retry when packs finish downloading.
        _CACHE[key] = (time.time() + 300.0, None)
        return None
    with _DISK_LOCK:
        disk = _load_disk()
        disk[key] = hit
        _DISK_DIRTY = True
        if len(disk) % 200 == 0:
            _save_disk()
    _set_cached(key, hit)
    return hit


def flush_geocode_cache() -> None:
    with _DISK_LOCK:
        _save_disk()


def resolve_search_area(
    *,
    place: str | None = None,
    postalcode: str | None = None,
    zip_code: str | None = None,
    country: str | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    latrange1: float | None = None,
    latrange2: float | None = None,
    longrange1: float | None = None,
    longrange2: float | None = None,
) -> dict:
    """
    Resolve location filters to a single bbox + geocode metadata.

    Priority: explicit bbox / lat-lon ranges > postalcode/zip > place name.
    """
    if bbox:
        return {"bbox": bbox, "geocode": None, "candidates": []}

    if None not in (latrange1, latrange2, longrange1, longrange2):
        south, north = sorted([latrange1, latrange2])  # type: ignore[type-var]
        west, east = sorted([longrange1, longrange2])  # type: ignore[type-var]
        return {
            "bbox": (west, south, east, north),
            "geocode": None,
            "candidates": [],
        }

    pc = (postalcode or zip_code or "").strip()
    if pc:
        candidates = geocode_postalcode(pc, country=country or "de")
        if not candidates:
            return {
                "bbox": None,
                "geocode": None,
                "candidates": [],
                "error": f"No match for postal code {pc}",
            }
        best = candidates[0]
        bb = best.get("bbox")
        if not bb:
            lon, lat = best["lon"], best["lat"]
            pad = 0.02
            bb = [lon - pad, lat - pad, lon + pad, lat + pad]
        return {
            "bbox": tuple(bb),
            "geocode": best,
            "candidates": candidates,
        }

    if place and place.strip():
        candidates = geocode_place(place.strip(), country=country)
        if not candidates:
            return {
                "bbox": None,
                "geocode": None,
                "candidates": [],
                "error": f"No match for place '{place}'",
            }
        best = candidates[0]
        bb = best.get("bbox")
        if not bb:
            lon, lat = best["lon"], best["lat"]
            pad = 0.03
            bb = [lon - pad, lat - pad, lon + pad, lat + pad]
        return {
            "bbox": tuple(bb),
            "geocode": best,
            "candidates": candidates,
        }

    return {"bbox": None, "geocode": None, "candidates": []}


@lru_cache(maxsize=256)
def normalize_mac(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = "".join(c for c in value.upper() if c in "0123456789ABCDEF")
    return cleaned or None


def mac_sql_pattern(normalized: str) -> str:
    return normalized
