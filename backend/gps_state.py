"""
In-memory GPS fix per user.

lat/lon are display + fog-unlock coords (road-snapped when enabled).
raw_lat/raw_lon preserve the unsnapped GPS reading.
stationary reflects the gpsd parked/idle filter (see gps_motion).
"""

from __future__ import annotations

import threading
import time
from typing import Any

_lock = threading.Lock()
_fixes: dict[int, dict[str, Any]] = {}


def get_fix(user_id: int) -> dict[str, Any] | None:
    with _lock:
        fix = _fixes.get(user_id)
        return dict(fix) if fix else None


def set_fix(
    user_id: int,
    *,
    lat: float,
    lon: float,
    heading_deg: float | None = None,
    speed_mps: float | None = None,
    accuracy_m: float | None = None,
    source: str = "client",
    level_id: int | None = None,
    session_started_at: str | None = None,
    raw_lat: float | None = None,
    raw_lon: float | None = None,
    snap: dict[str, Any] | None = None,
    snapped: bool | None = None,
    snap_dist_m: float | None = None,
    stationary: bool | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Returns (previous_fix_or_None, new_fix)."""
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("lat/lon out of range")
    fix: dict[str, Any] = {
        "lat": float(lat),
        "lon": float(lon),
        "heading_deg": float(heading_deg) if heading_deg is not None else None,
        "speed_mps": float(speed_mps) if speed_mps is not None else None,
        "accuracy_m": float(accuracy_m) if accuracy_m is not None else 15.0,
        "source": source,
        "level_id": level_id,
        "session_started_at": session_started_at,
        "raw_lat": float(raw_lat) if raw_lat is not None else float(lat),
        "raw_lon": float(raw_lon) if raw_lon is not None else float(lon),
        "stationary": bool(stationary) if stationary is not None else False,
        "updated_at": time.time(),
    }
    snap_meta = snap
    if snap_meta is None and (snapped is not None or snap_dist_m is not None):
        snap_meta = {
            "snapped": bool(snapped),
            "held": False,
            "degraded": not bool(snapped),
            "distance_m": snap_dist_m,
            "dist_m": snap_dist_m,
        }
    if snap_meta:
        fix["snapped"] = bool(snap_meta.get("snapped"))
        fix["snap_dist_m"] = snap_meta.get("distance_m", snap_meta.get("dist_m"))
        fix["snap"] = {
            "snapped": bool(snap_meta.get("snapped")),
            "held": bool(snap_meta.get("held")),
            "degraded": bool(snap_meta.get("degraded")),
            "distance_m": snap_meta.get("distance_m", snap_meta.get("dist_m")),
            "threshold_m": snap_meta.get("threshold_m"),
            "segment_id": snap_meta.get("segment_id"),
            "enabled": snap_meta.get("enabled", True),
        }
    with _lock:
        prev = _fixes.get(user_id)
        prev_copy = dict(prev) if prev else None
        _fixes[user_id] = fix
        return prev_copy, dict(fix)


def clear_fix(user_id: int) -> None:
    with _lock:
        _fixes.pop(user_id, None)
