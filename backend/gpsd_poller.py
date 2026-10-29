"""
Background gpsd client → gps_state.set_fix(source=gpsd).

Always-on for the collection user (fog unlock + XP + Kismet positions),
whether or not the Drive dashboard is open.

Parked/idle: gps_motion pauses unlock + drive XP when the raw receiver has
not moved ~100 m within 5 min (GPSD_STATIONARY_*). Fix updates still flow so
Drive / Kismet can read position and the stationary flag.

Runs on the API process. gpsd itself stays on the host; use
GPSD_HOST=host.docker.internal (Linux host-gateway) or 127.0.0.1 when
the API is on the host.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from typing import Any

_poller_started = False
_lock = threading.Lock()
_last_heading: float | None = None
_heading_moving = False
_session_started_at: dict[int, str] = {}
_last_fix_mono: dict[int, float] = {}
_last_unlock_at: dict[int, float] = {}
_last_unlock_pos: dict[int, tuple[Any, float | None, float | None]] = {}
_last_collection_user: int | None = None
_collection_user_cache: tuple[int, float] | None = None
# A gap without fixes this long starts a new drive session (HUD stats window).
_SESSION_IDLE_S = float(os.getenv("GPSD_SESSION_IDLE_S", "1800"))


def _moved_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math

    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def collection_user_id() -> int:
    """
    Always-on collection account for gpsd + Kismet (no Drive UI required).

    Prefer GPSD_USER_ID / KISMET_USER_ID, else the first user (admin).
    """
    global _collection_user_cache
    pinned = (os.getenv("GPSD_USER_ID") or os.getenv("KISMET_USER_ID") or "").strip()
    if pinned.isdigit():
        return int(pinned)
    cached = _collection_user_cache
    if cached and time.monotonic() - cached[1] < 60.0:
        return cached[0]
    uid = _lookup_first_user_id()
    _collection_user_cache = (uid, time.monotonic())
    return uid


def _lookup_first_user_id() -> int:
    try:
        from db import connect_dict

        conn = connect_dict()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1")
                row = cur.fetchone()
                if row and row.get("id") is not None:
                    return int(row["id"])
        finally:
            conn.close()
    except Exception:
        pass
    return 1


def _target_user_ids() -> list[int]:
    """gpsd always writes the collection user — independent of Drive open."""
    global _last_collection_user
    uid = collection_user_id()
    if _last_collection_user is not None and _last_collection_user != uid:
        _session_started_at.pop(_last_collection_user, None)
        try:
            from gps_snap import clear_last_good

            clear_last_good(_last_collection_user)
        except Exception:
            pass
        try:
            from gps_motion import tracker as motion_tracker

            motion_tracker.clear(_last_collection_user)
        except Exception:
            pass
    _last_collection_user = uid
    return [uid]


def _parse_tpv(msg: dict[str, Any]) -> dict[str, Any] | None:
    global _heading_moving, _last_heading
    mode = int(msg.get("mode") or 0)
    if mode < 2:
        return None
    lat = msg.get("lat")
    lon = msg.get("lon")
    if lat is None or lon is None:
        return None
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return None

    speed = msg.get("speed")
    try:
        speed_mps = float(speed) if speed is not None else None
    except (TypeError, ValueError):
        speed_mps = None

    track = msg.get("track")
    heading = None
    try:
        if track is not None:
            heading = float(track)
    except (TypeError, ValueError):
        heading = None

    # gpsd track is junk when parked. Separate start/stop thresholds prevent
    # speed noise around 0.4 m/s from repeatedly accepting random headings.
    if speed_mps is not None:
        if _heading_moving and speed_mps <= 0.3:
            _heading_moving = False
        elif not _heading_moving and speed_mps >= 0.6:
            _heading_moving = True
    if heading is not None and _heading_moving:
        _last_heading = heading
    elif _last_heading is not None:
        heading = _last_heading
    else:
        heading = None

    return {
        "lat": lat_f,
        "lon": lon_f,
        "heading_deg": heading,
        "speed_mps": speed_mps,
        "accuracy_m": 12.0,
        "mode": mode,
    }


def _apply_fix(user_id: int, fix: dict[str, Any]) -> None:
    from gps_motion import tracker as motion_tracker
    from gps_snap import resolve_drive_profile, resolve_level_id, snap_to_road
    from gps_state import get_fix, set_fix

    now_fix = time.monotonic()
    if (
        user_id not in _session_started_at
        or now_fix - _last_fix_mono.get(user_id, now_fix) > _SESSION_IDLE_S
    ):
        from datetime import datetime, timezone

        _session_started_at[user_id] = datetime.now(timezone.utc).isoformat()
    _last_fix_mono[user_id] = now_fix

    prev = get_fix(user_id)
    # Keep an active WASD debug session stable unless GPSD_USER_ID explicitly
    # pins this user to the hardware receiver.
    if (
        not os.getenv("GPSD_USER_ID", "").strip()
        and prev
        and prev.get("source") == "sim"
        and time.time() - float(prev.get("updated_at") or 0) < 5.0
    ):
        return

    # Motion filter uses raw receiver coords so road-snap cannot mask jitter
    # or invent lateral motion along a held segment.
    stationary = motion_tracker.update(user_id, fix["lat"], fix["lon"])

    level_id = resolve_level_id(user_id)
    profile = resolve_drive_profile(user_id, level_id)
    snap = snap_to_road(
        fix["lon"],
        fix["lat"],
        level_id,
        user_id=user_id,
        heading_deg=fix.get("heading_deg"),
        profile=profile,
    )
    use_lat = snap["lat"]
    use_lon = snap["lon"]

    set_fix(
        user_id,
        lat=use_lat,
        lon=use_lon,
        heading_deg=fix["heading_deg"],
        speed_mps=fix["speed_mps"],
        accuracy_m=fix["accuracy_m"],
        source="gpsd",
        level_id=level_id,
        session_started_at=_session_started_at[user_id],
        raw_lat=fix["lat"],
        raw_lon=fix["lon"],
        snap=snap,
        stationary=stationary,
    )
    if stationary:
        # Parked overnight: keep the live fix for Drive HUD / Kismet position,
        # but do not unlock fog, credit drive XP, or pile observation work.
        return

    unlock_stats = None
    unlock_interval = max(1.0, float(os.getenv("GPSD_UNLOCK_INTERVAL", "2.5")))
    now_mono = time.monotonic()
    # Car unlock only covers the snapped segment + one ahead (~40 m), so a pure
    # time throttle leaves fog holes above ~60 km/h. Skip only redundant work:
    # same segment and barely moved.
    last_seg, last_lat, last_lon = _last_unlock_pos.get(user_id, (None, None, None))
    seg_changed = snap.get("segment_id") != last_seg
    moved_m = (
        _moved_m(last_lat, last_lon, use_lat, use_lon)
        if last_lat is not None
        else float("inf")
    )
    if (
        seg_changed
        or moved_m >= 10.0
        or now_mono - _last_unlock_at.get(user_id, 0.0) >= unlock_interval
    ):
        try:
            from levels import get_level, unlock_near_point

            if level_id is not None:
                level = get_level(user_id, int(level_id))
                if level and level.get("status") == "ready":
                    unlock_lon = (
                        fix["lon"] if snap.get("snap_mode") == "distance" else use_lon
                    )
                    unlock_lat = (
                        fix["lat"] if snap.get("snap_mode") == "distance" else use_lat
                    )
                    unlock_stats = unlock_near_point(
                        int(level_id),
                        unlock_lon,
                        unlock_lat,
                        accuracy_m=fix.get("accuracy_m") or 12.0,
                        heading_deg=fix.get("heading_deg"),
                        segment_id=snap.get("segment_id"),
                        profile=profile,
                        user_id=user_id,
                    )
                    _last_unlock_at[user_id] = now_mono
                    _last_unlock_pos[user_id] = (
                        snap.get("segment_id"),
                        use_lat,
                        use_lon,
                    )
        except Exception:
            unlock_stats = None

    # Fog XP must be credited here — Drive uses gpsd, not POST /api/gps/fix.
    explored_km = 0.0
    if unlock_stats:
        if unlock_stats.get("newly_explored_m") is not None:
            explored_km = max(0.0, float(unlock_stats["newly_explored_m"]) / 1000.0)
        elif unlock_stats.get("newly_explored"):
            # ~20 m segments (SEGMENT_TARGET_M) when length sum unavailable
            explored_km = float(unlock_stats["newly_explored"]) * 0.02
    try:
        from achievements import record_drive_step

        record_drive_step(
            user_id,
            lat=use_lat,
            lon=use_lon,
            now_ts=time.time(),
            explored_km_delta=explored_km,
            speed_mps=fix.get("speed_mps"),
        )
    except Exception:
        pass


def _read_loop(host: str, port: int, interval: float) -> None:
    last_applied = 0.0
    while True:
        try:
            with socket.create_connection((host, port), timeout=2.0) as sock:
                sock.settimeout(2.0)
                sock.sendall(b'?WATCH={"enable":true,"json":true}\n')
                buf = b""
                closed = False
                while not closed:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                    # Drain everything already queued so a slow tick never
                    # leaves us applying positions from seconds ago.
                    sock.setblocking(False)
                    try:
                        while True:
                            more = sock.recv(65536)
                            if not more:
                                closed = True
                                break
                            buf += more
                    except (BlockingIOError, InterruptedError):
                        pass
                    finally:
                        sock.settimeout(2.0)
                    latest = None
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            msg = json.loads(line.decode("utf-8", errors="replace"))
                        except json.JSONDecodeError:
                            continue
                        if msg.get("class") != "TPV":
                            continue
                        fix = _parse_tpv(msg)
                        if fix:
                            latest = fix
                    if latest is None:
                        continue
                    now_mono = time.monotonic()
                    if now_mono - last_applied < interval:
                        continue
                    last_applied = now_mono
                    for uid in _target_user_ids():
                        try:
                            _apply_fix(uid, latest)
                        except Exception:
                            pass
        except OSError:
            time.sleep(3.0)
        except Exception:
            time.sleep(2.0)


def start_gpsd_poller() -> None:
    """Idempotent: spawn daemon thread if GPSD_ENABLED."""
    global _poller_started
    if not _env_bool("GPSD_ENABLED", True):
        return
    with _lock:
        if _poller_started:
            return
        _poller_started = True
    host = os.getenv("GPSD_HOST", "127.0.0.1")
    port = int(os.getenv("GPSD_PORT", "2947"))
    # 5 Hz default — cleaner course for Navigate smooth follow
    interval = float(os.getenv("GPSD_POLL_INTERVAL", "0.2"))
    t = threading.Thread(
        target=_read_loop,
        args=(host, port, interval),
        name="gpsd-poller",
        daemon=True,
    )
    t.start()
    print(f"[gpsd] poller started → {host}:{port} @ {1.0 / max(interval, 0.05):.0f} Hz")
