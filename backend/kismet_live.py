"""
Kismet live bridge: REST poll (+ optional WS) → live_ingest.

Primary: HTTP devices/last-time on KISMET_URL (:2501).
Fallback: watch .kismet / kis_db growth under KISMET_LOG_DIR and incremental parse.
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any

_started = False
_lock = threading.Lock()
_seen_keys: OrderedDict[str, None] = OrderedDict()
_session_started_at: str | None = None
_cookie_jar = CookieJar()
_http_opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(_cookie_jar)
)
_auth_probe_done = False
_auth_error_logged = False
_working_device_path: str | None = None
_rest_watermarks: dict[int, float] = {}

_REST_WATERMARK_KEY = "kismet_live_rest_watermark"
_FILE_WATERMARK_KEY = "kismet_live_file_watermarks"


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _auth_header() -> str | None:
    user = os.getenv("KISMET_USER", "").strip()
    password = os.getenv("KISMET_PASSWORD", "").strip()
    if not user:
        return None
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {token}"


def _base_url() -> str:
    return (os.getenv("KISMET_URL") or "http://127.0.0.1:2501").rstrip("/")


def _setting(user_id: int, key: str, default: str | None = None) -> str | None:
    try:
        from db import get_user_setting

        return get_user_setting(user_id, key, default)
    except Exception:
        return default


def _set_setting(user_id: int, key: str, value: str) -> None:
    try:
        from db import set_user_setting

        set_user_setting(user_id, key, value)
    except Exception:
        pass


def _remember_seen(keys: list[str]) -> None:
    limit = max(1000, int(os.getenv("KISMET_DEDUP_LIMIT", "50000")))
    for key in keys:
        _seen_keys[key] = None
        _seen_keys.move_to_end(key)
    while len(_seen_keys) > limit:
        _seen_keys.popitem(last=False)


def _target_user_id() -> int:
    pinned = os.getenv("KISMET_USER_ID") or os.getenv("GPSD_USER_ID") or ""
    if pinned.strip().isdigit():
        return int(pinned.strip())
    try:
        from db import connect_dict

        conn = connect_dict()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT user_id
                    FROM user_settings
                    WHERE key = 'navigation_active' AND lower(value) = 'true'
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
                if row and row.get("user_id") is not None:
                    return int(row["user_id"])
                cur.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1")
                row = cur.fetchone()
                if row and row.get("id") is not None:
                    return int(row["id"])
        finally:
            conn.close()
    except Exception:
        pass
    return 1


def _http_json(path: str, timeout: float = 4.0) -> Any | None:
    global _auth_error_logged
    url = f"{_base_url()}{path}"
    headers = {"Accept": "application/json"}
    auth = _auth_header()
    # A successful Basic-auth request may establish a Kismet session cookie.
    # Once present, let the cookie opener reuse it instead of re-sending credentials.
    if auth and not list(_cookie_jar):
        headers["Authorization"] = auth
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with _http_opener.open(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw.decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        # Some Kismet builds set non-auth cookies. If cookie-only access is
        # rejected, retry once with Basic while retaining the cookie jar.
        if exc.code in {401, 403} and auth and "Authorization" not in headers:
            retry_headers = dict(headers)
            retry_headers["Authorization"] = auth
            retry = urllib.request.Request(
                url, headers=retry_headers, method="GET"
            )
            try:
                with _http_opener.open(retry, timeout=timeout) as resp:
                    raw = resp.read()
                    return json.loads(raw.decode("utf-8", errors="replace"))
            except (
                urllib.error.URLError,
                urllib.error.HTTPError,
                TimeoutError,
                json.JSONDecodeError,
                OSError,
            ):
                pass
        if exc.code in {401, 403} and not _auth_error_logged:
            _auth_error_logged = True
            print(
                "[kismet_live] authentication rejected; check "
                "KISMET_USER/KISMET_PASSWORD against kismet_site.conf"
            )
        return None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def _probe_kismet() -> bool:
    global _auth_probe_done
    if _auth_probe_done:
        return True
    status = _http_json("/system/status.json")
    if status is None:
        return False
    _auth_probe_done = True
    mode = "session cookie" if list(_cookie_jar) else "HTTP Basic"
    print(f"[kismet_live] authenticated via {mode}; status endpoint ok")
    return True


def _phy_to_type(phy: str | None, type_name: str | None = None) -> str:
    blob = f"{phy or ''} {type_name or ''}".lower()
    if "ble" in blob or "btle" in blob:
        return "BLE"
    if "bluetooth" in blob or blob.strip() in {"bt", "br/edr"}:
        return "BT"
    if "802.11" in blob or "ieee802.11" in blob or "wifi" in blob or "wlan" in blob:
        return "WIFI"
    return "WIFI"


def _device_to_row(device: dict, user_id: int) -> tuple | None:
    """Build observation_tuple-compatible row or None."""
    from wigle import observation_tuple

    mac = (
        device.get("kismet.device.base.macaddr")
        or device.get("kismet.device.base.key")
        or ""
    )
    mac = str(mac).strip().lower().replace("-", ":")
    if not mac or mac == "00:00:00:00:00:00":
        return None

    # Prefer advertised SSID; Kismet commonname/base.name often equals the MAC.
    from wigle import sanitize_network_name

    name = None
    channel = None
    encryption = device.get("kismet.device.base.crypt")
    if isinstance(encryption, str):
        encryption = encryption.strip() or None
    else:
        encryption = None

    dot11 = device.get("dot11.device")
    if isinstance(dot11, dict):
        last_ssid = dot11.get("dot11.device.last_beaconed_ssid_record") or {}
        if isinstance(last_ssid, dict):
            name = last_ssid.get("dot11.advertisedssid.ssid") or None
            channel = last_ssid.get("dot11.advertisedssid.channel") or channel
            if not encryption:
                encryption = last_ssid.get("dot11.advertisedssid.crypt_string") or last_ssid.get(
                    "dot11.advertisedssid.crypt_set"
                )
    if not name:
        name = device.get("kismet.device.base.commonname") or device.get(
            "kismet.device.base.name"
        )
    name = sanitize_network_name(name, mac)

    phy = device.get("kismet.device.base.phyname")
    type_name = device.get("kismet.device.base.type")
    ntype = _phy_to_type(str(phy) if phy else None, str(type_name) if type_name else None)

    signal = None
    sig = device.get("kismet.device.base.signal") or {}
    if isinstance(sig, dict):
        signal = sig.get("kismet.common.signal.last_signal")

    lat = lon = alt = None
    loc = device.get("kismet.device.base.location") or {}
    if isinstance(loc, dict):
        avg = loc.get("kismet.common.location.avg_loc") or loc.get(
            "kismet.common.location.min_loc"
        )
        if isinstance(avg, dict):
            gp = avg.get("kismet.common.location.geopoint")
            if isinstance(gp, (list, tuple)) and len(gp) >= 2:
                lon, lat = float(gp[0]), float(gp[1])
            alt = avg.get("kismet.common.location.alt")
        lat = loc.get("kismet.common.location.avg_lat", lat)
        lon = loc.get("kismet.common.location.avg_lon", lon)

    if lat is None or lon is None:
        try:
            from gps_state import get_fix

            fix = get_fix(user_id)
            if fix and fix.get("lat") is not None:
                lat = float(fix["lat"])
                lon = float(fix["lon"])
        except Exception:
            pass
    if lat is None or lon is None:
        return None

    last_time = device.get("kismet.device.base.last_time")
    if isinstance(last_time, (int, float)) and last_time > 0:
        ts = float(last_time)
        if ts > 1e12:
            ts /= 1000.0
        seen_at = datetime.fromtimestamp(ts, tz=timezone.utc)
    else:
        seen_at = datetime.now(timezone.utc)

    record = {
        "network_id": mac,
        "name": name,
        "encryption": encryption,
        "network_type": ntype,
        "channel": channel,
        "signal": signal,
        "lat": float(lat),
        "lon": float(lon),
        "altitude": float(alt) if alt is not None else None,
        "accuracy": 15.0,
        "seen_at": seen_at,
    }
    try:
        return observation_tuple(record, source_file="kismet_live", source_format="kismet")
    except Exception:
        return None


def _device_time(device: dict) -> float | None:
    value = device.get("kismet.device.base.last_time")
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    ts = float(value)
    return ts / 1000.0 if ts > 1e12 else ts


def _ingest_devices(devices: list[dict]) -> tuple[int, float | None]:
    global _session_started_at
    if not devices:
        return 0, None
    user_id = _target_user_id()
    try:
        from gps_state import get_fix

        fix = get_fix(user_id)
        if fix and fix.get("session_started_at"):
            _session_started_at = str(fix["session_started_at"])
    except Exception:
        pass
    if not _session_started_at:
        _session_started_at = datetime.now(timezone.utc).isoformat()
    rows = []
    pending_keys: list[str] = []
    pending_key_set: set[str] = set()
    committed_through: float | None = None
    for d in devices:
        if not isinstance(d, dict):
            continue
        mac = str(
            d.get("kismet.device.base.macaddr")
            or d.get("kismet.device.base.key")
            or ""
        ).lower()
        seen_ts = _device_time(d)
        key = f"rest:{mac}:{seen_ts}"
        if key in _seen_keys or key in pending_key_set:
            if seen_ts is not None:
                committed_through = max(committed_through or seen_ts, seen_ts)
            continue
        row = _device_to_row(d, user_id)
        if not row:
            continue
        rows.append(row)
        pending_keys.append(key)
        pending_key_set.add(key)
        if seen_ts is not None:
            committed_through = max(committed_through or seen_ts, seen_ts)
    if not rows:
        return 0, committed_through
    try:
        from live_ingest import ingest_observation_batch

        result = ingest_observation_batch(
            user_id, rows, localize=True, enqueue_geocode=False
        )
        _remember_seen(pending_keys)
        return int(result.get("samples") or 0), committed_through
    except Exception as exc:
        print(f"[kismet_live] ingest error: {exc}")
        return 0, None


def _poll_rest_once() -> int:
    """Fetch recently active devices via REST."""
    global _working_device_path
    if not _probe_kismet():
        return 0

    user_id = _target_user_id()
    if user_id not in _rest_watermarks:
        raw = _setting(user_id, _REST_WATERMARK_KEY, "0") or "0"
        try:
            _rest_watermarks[user_id] = float(raw)
        except (TypeError, ValueError):
            _rest_watermarks[user_id] = 0.0
    watermark = _rest_watermarks[user_id]
    since = str(int(watermark) + 1) if watermark > 0 else "-30"
    fields = (
        "kismet.device.base.macaddr,kismet.device.base.key,"
        "kismet.device.base.name,kismet.device.base.commonname,"
        "kismet.device.base.phyname,kismet.device.base.type,"
        "kismet.device.base.signal,kismet.device.base.location,"
        "kismet.device.base.last_time,kismet.device.base.crypt,dot11.device"
    )
    paths = [
        f"/devices/last-time/{since}/devices.json",
        f"/devices/views/all/devices.json?fields={fields}",
        "/devices/all_devices.json",
    ]
    if _working_device_path and _working_device_path != "last-time":
        paths = [_working_device_path] + [p for p in paths if p != _working_device_path]

    data = None
    used_path = None
    for path in paths:
        data = _http_json(path)
        if data is not None:
            used_path = path
            break
    if data is None:
        return 0
    path_kind = "last-time" if used_path and used_path.startswith("/devices/last-time/") else used_path
    if path_kind and path_kind != _working_device_path:
        _working_device_path = path_kind
        print(f"[kismet_live] devices endpoint: {used_path.split('?', 1)[0]}")
    if isinstance(data, dict):
        devices = data.get("devices") or data.get("data") or []
        if isinstance(devices, dict):
            devices = list(devices.values())
    elif isinstance(data, list):
        devices = data
    else:
        return 0
    if not devices:
        return -1  # REST is healthy; there is simply nothing new.
    fresh_devices = []
    for device in devices:
        if not isinstance(device, dict):
            continue
        seen_ts = _device_time(device)
        if watermark > 0 and seen_ts is not None and seen_ts <= watermark:
            continue
        fresh_devices.append(device)
    if not fresh_devices:
        return -1
    count, committed_through = _ingest_devices(fresh_devices)
    if committed_through is not None and committed_through > watermark:
        _rest_watermarks[user_id] = committed_through
        _set_setting(user_id, _REST_WATERMARK_KEY, str(committed_through))
    return count


def _fallback_kis_db() -> int:
    """Parse newest .kismet / .kis_db incrementally using a persisted watermark."""
    log_dir = Path(os.getenv("KISMET_LOG_DIR") or "/data/kismet_logs")
    if not log_dir.is_dir():
        alt = Path(__file__).resolve().parents[1] / "data" / "incoming" / "Kismet_Out"
        log_dir = alt if alt.is_dir() else log_dir
    if not log_dir.is_dir():
        return 0

    candidates = sorted(
        list(log_dir.rglob("*.kismet")) + list(log_dir.rglob("*.kis_db")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return 0
    path = candidates[0]
    try:
        from kismet import is_kismet_db, parse_kismet_db

        if not is_kismet_db(path):
            return 0
        user_id = _target_user_id()
        parsed = parse_kismet_db(path)
        raw_state = _setting(user_id, _FILE_WATERMARK_KEY, "{}") or "{}"
        try:
            watermark_state = json.loads(raw_state)
            if not isinstance(watermark_state, dict):
                watermark_state = {}
        except (TypeError, ValueError, json.JSONDecodeError):
            watermark_state = {}
        state_key = str(path)
        saved = watermark_state.get(state_key) or {}
        saved_ts = float(saved.get("ts") or 0)
        saved_keys = set(saved.get("keys") or [])

        def row_ts(row: tuple) -> float:
            seen = row[3] if len(row) > 3 else None
            if isinstance(seen, datetime):
                return seen.timestamp()
            return 0.0

        parsed.sort(key=row_ts)
        rows = []
        pending_keys: list[str] = []
        pending_key_set: set[str] = set()
        max_ts = saved_ts
        max_ts_keys = set(saved_keys)
        # A first fallback only needs the freshest bounded window; later runs use
        # the persisted timestamp and same-second keys.
        candidates = parsed[-1000:] if saved_ts <= 0 else parsed
        for row in candidates:
            ts = row_ts(row)
            key = f"{row[1]}:{ts}"
            if ts < saved_ts or (ts == saved_ts and key in saved_keys):
                continue
            dedup_key = f"file:{path.name}:{key}"
            if dedup_key in _seen_keys or dedup_key in pending_key_set:
                continue
            if ts > max_ts:
                max_ts = ts
                max_ts_keys = {key}
            elif ts == max_ts:
                max_ts_keys.add(key)
            pending_keys.append(dedup_key)
            pending_key_set.add(dedup_key)
            rows.append(row)
        if not rows:
            return 0
        from live_ingest import ingest_observation_batch

        result = ingest_observation_batch(
            user_id, rows, localize=True, enqueue_geocode=False
        )
        _remember_seen(pending_keys)
        watermark_state[state_key] = {
            "ts": max_ts,
            "keys": sorted(max_ts_keys),
        }
        # Keep only the most recent log files so user_settings stays bounded.
        if len(watermark_state) > 8:
            ordered = sorted(
                watermark_state.items(),
                key=lambda item: float((item[1] or {}).get("ts") or 0),
                reverse=True,
            )
            watermark_state = dict(ordered[:8])
        _set_setting(
            user_id,
            _FILE_WATERMARK_KEY,
            json.dumps(watermark_state, separators=(",", ":")),
        )
        return int(result.get("samples") or 0)
    except Exception as exc:
        print(f"[kismet_live] kis_db fallback: {exc}")
        return 0


def _loop() -> None:
    rest_fail = 0
    while True:
        try:
            n = _poll_rest_once()
            if n < 0:
                rest_fail = 0
            elif n == 0:
                rest_fail += 1
            else:
                rest_fail = 0
            # After several empty/failed REST polls, try file fallback
            if rest_fail >= 5:
                _fallback_kis_db()
                rest_fail = 0
        except Exception as exc:
            print(f"[kismet_live] loop: {exc}")
            try:
                _fallback_kis_db()
            except Exception:
                pass
        time.sleep(float(os.getenv("KISMET_POLL_INTERVAL", "2.5")))


def start_kismet_live() -> None:
    global _started
    if not _env_bool("KISMET_LIVE", True):
        return
    with _lock:
        if _started:
            return
        _started = True
    t = threading.Thread(target=_loop, name="kismet-live", daemon=True)
    t.start()
    print(f"[kismet_live] bridge started → {_base_url()}")
