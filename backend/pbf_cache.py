"""
Regional Geofabrik PBF cache under data/pbf/.

These packs are download caches for region prepare / level build / Valhalla clip.
Live Drive routing uses Valhalla tiles + data/valhalla/active.osm.pbf — not the
regional pack. Packs are retained for PBF_CACHE_DAYS (default 7), touched on use,
and pruned hourly (and on demand via Status → Free storage).
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from paths import DATA

PBF_DIR = DATA / "pbf"
RETENTION_DAYS = max(1, int(os.getenv("PBF_CACHE_DAYS", "7")))
CLEAN_INTERVAL_S = max(60.0, float(os.getenv("PBF_CACHE_CLEAN_INTERVAL_S", "3600")))
MIN_PACK_BYTES = 1000

_cleaner_started = False
_lock = threading.Lock()
_cleaner_lock = threading.Lock()


def _bytes_human(n: int | None) -> str | None:
    if n is None:
        return None
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


def retention_seconds() -> float:
    return float(RETENTION_DAYS) * 86400.0


def touch_pack(path: Path | None) -> None:
    """Renew the 7-day cache lease when a pack is reused."""
    if path is None:
        return
    try:
        if path.is_file() and path.stat().st_size >= MIN_PACK_BYTES:
            os.utime(path, None)
    except OSError:
        pass


def list_cached_packs() -> list[dict[str, Any]]:
    """Complete regional packs in data/pbf (*.osm.pbf / *.pbf), excluding .part."""
    if not PBF_DIR.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(PBF_DIR.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file():
            continue
        name = path.name
        lower = name.lower()
        if lower.endswith(".part") or lower.endswith(".tmp") or ".tmp." in lower:
            continue
        if not (lower.endswith(".osm.pbf") or lower.endswith(".pbf")):
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        if st.st_size < MIN_PACK_BYTES:
            continue
        out.append(
            {
                "path": path,
                "name": name,
                "size_bytes": int(st.st_size),
                "mtime": float(st.st_mtime),
                "age_s": max(0.0, time.time() - float(st.st_mtime)),
            }
        )
    return out


def cache_stats() -> dict[str, Any]:
    packs = list_cached_packs()
    total = sum(int(p["size_bytes"]) for p in packs)
    return {
        "map_packs_count": len(packs),
        "map_packs_bytes": total,
        "map_packs_human": _bytes_human(total),
        "map_packs_retention_days": RETENTION_DAYS,
        "map_packs_dir": str(PBF_DIR),
    }


def _payload_dict(payload: Any) -> dict:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str) and payload.strip():
        try:
            data = json.loads(payload)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _paths_for_extract_id(extract_id: str) -> set[Path]:
    eid = (extract_id or "").strip()
    if not eid:
        return set()
    from admin_areas import pbf_path_for_extract

    paths = {pbf_path_for_extract(eid).resolve()}
    short = eid.split("/")[-1]
    if short:
        paths.add((PBF_DIR / f"{short}.osm.pbf").resolve())
        paths.add((PBF_DIR / f"{short}.pbf").resolve())
    return paths


def protected_pack_paths() -> set[Path]:
    """
    Packs that must not be deleted: in-progress downloads (.part siblings) and
    extracts referenced by queued/running prepare/build jobs or active level builds.
    """
    protected: set[Path] = set()
    if PBF_DIR.is_dir():
        for path in PBF_DIR.iterdir():
            if not path.is_file():
                continue
            lower = path.name.lower()
            if lower.endswith(".part") or lower.endswith(".tmp") or ".tmp." in lower:
                # Protect both the partial and the eventual destination name.
                protected.add(path.resolve())
                stem = path.name
                if stem.endswith(".part"):
                    protected.add((PBF_DIR / stem[: -len(".part")]).resolve())
                continue

    extract_ids: set[str] = set()
    level_ids: set[int] = set()
    try:
        from db import connect

        conn = connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT job_type, payload
                    FROM jobs
                    WHERE status IN ('queued', 'running')
                      AND job_type = ANY(%s)
                    """,
                    (["prepare_place", "geofabrik_level", "level_addresses"],),
                )
                for job_type, payload in cur.fetchall() or []:
                    data = _payload_dict(payload)
                    gid = (data.get("geofabrik_id") or "").strip()
                    if gid:
                        extract_ids.add(gid)
                    lid = data.get("level_id")
                    if lid is not None:
                        try:
                            level_ids.add(int(lid))
                        except (TypeError, ValueError):
                            pass

                if level_ids:
                    cur.execute(
                        """
                        SELECT DISTINCT geofabrik_id
                        FROM levels
                        WHERE id = ANY(%s)
                          AND geofabrik_id IS NOT NULL
                          AND TRIM(geofabrik_id) <> ''
                        """,
                        (list(level_ids),),
                    )
                    for (gid,) in cur.fetchall() or []:
                        if gid:
                            extract_ids.add(str(gid).strip())

                cur.execute(
                    """
                    SELECT DISTINCT geofabrik_id
                    FROM levels
                    WHERE status IN ('processing', 'segmentizing')
                      AND geofabrik_id IS NOT NULL
                      AND TRIM(geofabrik_id) <> ''
                    """
                )
                for (gid,) in cur.fetchall() or []:
                    if gid:
                        extract_ids.add(str(gid).strip())
        finally:
            conn.close()
    except Exception as exc:
        # Fail closed: caller must not delete while we cannot see in-progress work.
        raise RuntimeError(f"protected pack lookup failed: {exc}") from exc

    for eid in extract_ids:
        protected |= _paths_for_extract_id(eid)
    return protected


def purge_cached_packs(
    *,
    max_age_s: float | None = None,
    unused_only: bool = True,
) -> dict[str, Any]:
    """
    Delete regional packs under data/pbf/.

    - max_age_s: only delete packs whose mtime is older than this (None = any age)
    - unused_only: skip packs protected by in-progress prepare/build work
    """
    with _cleaner_lock:
        packs = list_cached_packs()
        protected: set[Path] = set()
        if unused_only:
            try:
                protected = protected_pack_paths()
            except Exception as exc:
                print(f"[pbf-cache] skip purge (safety): {exc}", flush=True)
                return {
                    "ok": False,
                    "error": str(exc),
                    "deleted_count": 0,
                    "deleted": [],
                    "freed_bytes": 0,
                    "freed_human": "0 B",
                    "kept_protected": len(packs),
                    "kept_fresh": 0,
                    "remaining_count": len(packs),
                    "retention_days": RETENTION_DAYS,
                    "max_age_s": max_age_s,
                }
        deleted: list[dict[str, Any]] = []
        kept_protected = 0
        kept_fresh = 0
        freed = 0
        now = time.time()

        for pack in packs:
            path: Path = pack["path"]
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            if unused_only and resolved in protected:
                kept_protected += 1
                continue
            if max_age_s is not None and (now - float(pack["mtime"])) < max_age_s:
                kept_fresh += 1
                continue
            try:
                size = int(pack["size_bytes"])
                path.unlink(missing_ok=True)
            except OSError as exc:
                print(f"[pbf-cache] delete failed {path}: {exc}", flush=True)
                continue
            freed += size
            deleted.append(
                {
                    "name": pack["name"],
                    "size_bytes": size,
                    "age_s": round(float(pack["age_s"]), 1),
                }
            )

        return {
            "ok": True,
            "deleted_count": len(deleted),
            "deleted": deleted,
            "freed_bytes": freed,
            "freed_human": _bytes_human(freed),
            "kept_protected": kept_protected,
            "kept_fresh": kept_fresh,
            "remaining_count": len(packs) - len(deleted),
            "retention_days": RETENTION_DAYS,
            "max_age_s": max_age_s,
        }


def clean_expired_packs() -> dict[str, Any]:
    """Hourly job: drop unused packs older than the retention window."""
    return purge_cached_packs(max_age_s=retention_seconds(), unused_only=True)


def free_unused_packs() -> dict[str, Any]:
    """Status button: delete all unused cached packs now (any age)."""
    return purge_cached_packs(max_age_s=None, unused_only=True)


def _cleaner_loop() -> None:
    # First pass shortly after boot so long-idle cars reclaim space without waiting
    # a full hour; then every CLEAN_INTERVAL_S.
    time.sleep(15.0)
    while True:
        try:
            result = clean_expired_packs()
            if result.get("deleted_count"):
                print(
                    f"[pbf-cache] cleaned {result['deleted_count']} pack(s), "
                    f"freed {result.get('freed_human')}",
                    flush=True,
                )
        except Exception as exc:
            print(f"[pbf-cache] cleaner error: {exc}", flush=True)
        time.sleep(CLEAN_INTERVAL_S)


def start_pbf_cache_cleaner() -> None:
    """Idempotent: spawn daemon thread that prunes expired regional packs hourly."""
    global _cleaner_started
    if not _env_bool("PBF_CACHE_CLEANER_ENABLED", True):
        return
    with _lock:
        if _cleaner_started:
            return
        _cleaner_started = True
    PBF_DIR.mkdir(parents=True, exist_ok=True)
    t = threading.Thread(
        target=_cleaner_loop,
        name="pbf-cache-cleaner",
        daemon=True,
    )
    t.start()
    print(
        f"[pbf-cache] cleaner started · retain {RETENTION_DAYS}d · "
        f"every {CLEAN_INTERVAL_S:.0f}s → {PBF_DIR}",
        flush=True,
    )


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
