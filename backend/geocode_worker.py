"""
Parallel reverse-geocode for triangulated networks.

Uses all logical CPUs (hyperthreads) when navigation is idle.
When turn-by-turn is active, runs fewer workers at low OS thread priority
so routing stays responsive.
"""

from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable

try:
    from db import connect, get_user_setting
except ModuleNotFoundError:
    from backend.db import connect, get_user_setting

CHUNK = 400


def logical_thread_count() -> int:
    """Logical processors (SMT / hyperthreads), not physical cores."""
    return max(1, os.cpu_count() or 1)


def navigation_active(user_id: int | None = None) -> bool:
    if user_id is None:
        return False
    try:
        val = (get_user_setting(user_id, "navigation_active", "false") or "false").lower()
        return val in {"1", "true", "yes", "on"}
    except Exception:
        return False


def geocode_worker_count(*, nav_active: bool = False) -> int:
    n = logical_thread_count()
    if nav_active:
        return max(1, n // 4)
    return n


def _set_thread_low_priority() -> None:
    try:
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.kernel32.SetThreadPriority(
                ctypes.windll.kernel32.GetCurrentThread(), -2
            )
        else:
            try:
                os.nice(5)
            except OSError:
                pass
    except Exception:
        pass


def _geocode_one(lat: float, lon: float) -> dict | None:
    try:
        from geocode import reverse_geocode_cached
    except ModuleNotFoundError:
        from backend.geocode import reverse_geocode_cached
    return reverse_geocode_cached(float(lat), float(lon))


def _fields_from_geo(geo: dict | None) -> dict:
    if not geo:
        return {
            "address": None,
            "city": None,
            "postcode": None,
            "country": None,
            "country_code": None,
        }
    addr = geo.get("address") or {}
    return {
        "address": geo.get("display_name"),
        "city": addr.get("city")
        or addr.get("town")
        or addr.get("village")
        or addr.get("municipality"),
        "postcode": addr.get("postcode"),
        "country": addr.get("country"),
        "country_code": addr.get("country_code"),
    }


UPDATE_ADDR_SQL = """
UPDATE networks SET
    address = COALESCE(%(address)s, address),
    city = COALESCE(%(city)s, city),
    postcode = COALESCE(%(postcode)s, postcode),
    country = COALESCE(%(country)s, country),
    country_code = COALESCE(%(country_code)s, country_code)
WHERE user_id = %(user_id)s AND network_id = %(network_id)s
"""


def _work_row(row, nav: bool) -> dict | None:
    if nav:
        _set_thread_low_priority()
    uid, nid, lat, lon = row[0], row[1], float(row[2]), float(row[3])
    geo = _geocode_one(lat, lon)
    # Miss: leave the row alone so a later job (after address packs) can retry.
    if not geo:
        return None
    fields = _fields_from_geo(geo)
    fields["user_id"] = uid
    fields["network_id"] = nid
    return fields


def geocode_networks(
    *,
    user_id: int | None = None,
    network_ids: Iterable[str] | None = None,
    only_missing: bool = True,
    progress_cb=None,
) -> dict:
    """
    Fill address fields for networks that already have lat/lon.
    Does not recompute positions — call after localize so the map is ready first.
    """
    nav = navigation_active(user_id)
    workers = geocode_worker_count(nav_active=nav)
    if nav:
        _set_thread_low_priority()

    print("[geocode] loading network rows…", flush=True)
    conn = connect()
    try:
        with conn.cursor() as cur:
            sql = """
                SELECT user_id, network_id, lat, lon
                FROM networks
                WHERE lat IS NOT NULL AND lon IS NOT NULL
            """
            params: list = []
            if user_id is not None:
                sql += " AND user_id = %s"
                params.append(user_id)
            if network_ids is not None:
                ids = list(network_ids)
                if not ids:
                    return {"updated": 0, "workers": workers, "nav_active": nav}
                sql += " AND network_id = ANY(%s)"
                params.append(ids)
            if only_missing:
                sql += " AND (address IS NULL OR btrim(address) = '')"
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()

    total = len(rows)
    print(f"[geocode] {total} rows, workers={workers}, nav={nav}", flush=True)
    if total == 0:
        return {"updated": 0, "total": 0, "workers": workers, "nav_active": nav}

    updated = 0
    conn = connect()
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for start in range(0, total, CHUNK):
                chunk = rows[start : start + CHUNK]
                futures = [pool.submit(_work_row, row, nav) for row in chunk]
                batch: list[dict] = []
                for fut in as_completed(futures):
                    try:
                        item = fut.result()
                        if item:
                            batch.append(item)
                    except Exception as exc:
                        print(f"[geocode] worker error: {exc}", flush=True)
                if batch:
                    with conn.cursor() as cur:
                        for item in batch:
                            cur.execute(UPDATE_ADDR_SQL, item)
                    conn.commit()
                    updated += len(batch)
                    if progress_cb:
                        progress_cb(updated / total, updated, total)
                    print(
                        f"[geocode] {updated}/{total} workers={workers} nav={nav}",
                        flush=True,
                    )
                if nav:
                    import time

                    time.sleep(0.05)
    finally:
        conn.close()

    try:
        from geocode import flush_geocode_cache
    except ModuleNotFoundError:
        from backend.geocode import flush_geocode_cache
    flush_geocode_cache()

    return {
        "updated": updated,
        "total": total,
        "workers": workers,
        "nav_active": nav,
        "logical_threads": logical_thread_count(),
    }
