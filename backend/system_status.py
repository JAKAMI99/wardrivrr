from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path

from db import connect, db_kwargs

ROOT = Path(__file__).resolve().parents[1]
INCOMING = ROOT / "data" / "incoming"

# Cached /proc/stat sample for CPU % between Status polls
_cpu_sample: tuple[float, float, float] | None = None  # idle, total, monotonic

KISMET_CONTAINER = "wardrivrr_kismet"
POSTGIS_CONTAINER = "wardrivrr_postgis"
VALHALLA_CONTAINER = "wardrivrr_valhalla"


def deployment_mode() -> str:
    mode = (os.getenv("WARDIVRR_MODE") or "full").strip().lower()
    return mode if mode in {"full", "database"} else "full"


def deployment_expected(mode: str | None = None) -> dict[str, bool]:
    mode = mode or deployment_mode()
    if mode == "database":
        return {
            "gps": False,
            "kismet": False,
            "valhalla": False,
            "postgis": True,
            "database": True,
            "storage": True,
        }
    return {
        "gps": True,
        "kismet": True,
        "valhalla": True,
        "postgis": True,
        "database": True,
        "storage": True,
    }


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


def dir_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total


def docker_available() -> bool:
    return shutil.which("docker") is not None


def _docker_inspect(name: str) -> dict | None:
    try:
        proc = subprocess.run(
            ["docker", "inspect", name],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return data[0] if data else None


def container_status(name: str) -> dict:
    """Optional Docker enrichment. Prefer HTTP probes - API may lack docker CLI."""
    if not docker_available():
        return {
            "ok": False,
            "running": False,
            "found": False,
            "name": name,
            "status": "docker unavailable",
            "detail": None,
            "docker_cli": False,
        }
    info = _docker_inspect(name)
    if info:
        state = info.get("State") or {}
        running = bool(state.get("Running"))
        return {
            "ok": running,
            "running": running,
            "found": True,
            "name": name,
            "status": state.get("Status") or ("running" if running else "stopped"),
            "started_at": state.get("StartedAt"),
            "health": (state.get("Health") or {}).get("Status"),
            "image": (info.get("Config") or {}).get("Image"),
            "docker_cli": True,
        }
    return {
        "ok": False,
        "running": False,
        "found": False,
        "name": name,
        "status": "not found",
        "detail": None,
        "docker_cli": True,
    }


def _http_ok(
    url: str,
    timeout_s: float = 2.0,
    *,
    username: str | None = None,
    password: str | None = None,
) -> tuple[bool, str | None]:
    import base64
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(url, method="GET")
        if username is not None:
            token = base64.b64encode(
                f"{username}:{password or ''}".encode("utf-8")
            ).decode("ascii")
            req.add_header("Authorization", f"Basic {token}")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return 200 <= resp.status < 300, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return False, "HTTP 401 - check KISMET_USER / KISMET_PASSWORD match kismet_site.conf"
        return False, f"HTTP {exc.code}"
    except Exception as exc:
        return False, str(exc)


def _http_json(
    url: str,
    timeout_s: float = 2.5,
    *,
    username: str | None = None,
    password: str | None = None,
) -> tuple[object | None, str | None]:
    import base64
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(url, method="GET")
        if username is not None:
            token = base64.b64encode(
                f"{username}:{password or ''}".encode("utf-8")
            ).decode("ascii")
            req.add_header("Authorization", f"Basic {token}")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw), None
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except Exception as exc:
        return None, str(exc)


def _parse_kismet_source_line(line: str) -> dict | None:
    """Parse `source=iface:name=...:type=...` from kismet_site.conf."""
    s = line.strip()
    if not s.startswith("source=") or s.startswith("#"):
        return None
    body = s[len("source=") :].strip()
    if not body:
        return None
    parts = body.split(":")
    interface = parts[0].strip() or None
    name = None
    stype = None
    for part in parts[1:]:
        if "=" not in part:
            continue
        key, val = part.split("=", 1)
        key = key.strip().lower()
        val = val.strip()
        if key == "name":
            name = val
        elif key == "type":
            stype = val
    return {
        "interface": interface,
        "name": name,
        "type": stype,
        "running": None,
        "source": "config",
    }


def _kismet_sources_from_conf() -> list[dict]:
    candidates = [
        ROOT / "deploy" / "kismet" / "kismet_site.conf",
        Path("/etc/kismet/kismet_site.conf"),
    ]
    out: list[dict] = []
    for path in candidates:
        try:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for line in text.splitlines():
            parsed = _parse_kismet_source_line(line)
            if parsed:
                out.append(parsed)
        if out:
            break
    return out


def _kismet_sources_from_http(
    base: str, *, username: str, password: str
) -> list[dict]:
    """Prefer live datasources from Kismet HTTP API."""
    urls = [
        f"{base}/datasource/all_sources.json",
        f"{base}/datasource/sources.json",
    ]
    payload = None
    for url in urls:
        data, _err = _http_json(url, username=username or None, password=password)
        if data is not None:
            payload = data
            break
    if payload is None:
        return []

    rows: list = []
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        for key in (
            "datasource.list",
            "datasources",
            "sources",
            "kismet.datasource.list",
        ):
            val = payload.get(key)
            if isinstance(val, list):
                rows = val
                break
        if not rows:
            # Some builds nest under a single object keyed by UUID
            for val in payload.values():
                if isinstance(val, dict) and (
                    "kismet.datasource.interface" in val
                    or "kismet.datasource.type" in val
                ):
                    rows.append(val)

    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        interface = (
            row.get("kismet.datasource.interface")
            or row.get("interface")
            or row.get("kismet.datasource.capture_interface")
        )
        name = row.get("kismet.datasource.name") or row.get("name")
        stype = row.get("kismet.datasource.type") or row.get("type")
        running = row.get("kismet.datasource.running")
        if running is None:
            running = row.get("running")
        out.append(
            {
                "interface": interface,
                "name": name,
                "type": stype,
                "running": running,
                "source": "http",
            }
        )
    return out


def _classify_kismet_radios(sources: list[dict]) -> dict:
    wifi = {"present": False, "interface": None, "name": None}
    bluetooth = {"present": False, "interface": None}
    summaries: list[dict] = []
    for src in sources:
        stype = (src.get("type") or "").lower()
        iface = src.get("interface")
        name = src.get("name")
        summaries.append(
            {
                "interface": iface,
                "name": name,
                "type": src.get("type"),
                "running": src.get("running"),
                "source": src.get("source"),
            }
        )
        is_wifi = "wifi" in stype or "wlan" in stype or stype in {
            "linuxwifi",
            "nexmon",
            "hak5wifi",
        }
        is_bt = "bluetooth" in stype or "ble" in stype or stype in {
            "linuxbluetooth",
            "nrf",
        }
        # Heuristic when type missing: wlx*/wlan* -> wifi, hci* -> bluetooth
        if not stype and iface:
            il = str(iface).lower()
            if il.startswith(("wlx", "wlan", "wlp", "mon")):
                is_wifi = True
            elif il.startswith("hci"):
                is_bt = True
        if is_wifi and not wifi["present"]:
            wifi = {
                "present": True,
                "interface": iface,
                "name": name,
            }
        if is_bt and not bluetooth["present"]:
            bluetooth = {"present": True, "interface": iface}
    return {"wifi": wifi, "bluetooth": bluetooth, "sources": summaries}


def _active_pbf_ready() -> bool:
    try:
        from valhalla_prep import active_pbf_ready

        return active_pbf_ready()
    except Exception:
        return False


def _regional_pbf_ready() -> bool:
    try:
        from valhalla_prep import list_regional_pbfs

        return bool(list_regional_pbfs())
    except Exception:
        return False


def kismet_service_status() -> dict:
    """Host or Docker Kismet - probe HTTP with Basic auth from .env."""
    base = (os.getenv("KISMET_URL") or "http://127.0.0.1:2501").rstrip("/")
    # Prefer localhost when .env still has the old Docker-bridge hostname
    if "host.docker.internal" in base:
        base = "http://127.0.0.1:2501"
    try:
        from machine_setup import kismet_credentials

        user, password = kismet_credentials()
    except Exception:
        user = os.getenv("KISMET_USER") or ""
        password = os.getenv("KISMET_PASSWORD") or ""
    url = f"{base}/system/status.json"
    ok, detail = _http_ok(url, username=user or None, password=password)
    out = container_status(KISMET_CONTAINER)
    out["url"] = base
    out["http_ok"] = ok
    if ok:
        out["ok"] = True
        out["running"] = True
        out["found"] = True
        out["status"] = "reachable"
        out["detail"] = detail or f"HTTP OK at {base}"
    else:
        out["detail"] = detail or (
            f"Kismet not reachable at {base} - is kismet.service running?"
        )

    sources: list[dict] = []
    if ok:
        sources = _kismet_sources_from_http(base, username=user, password=password)
    if not sources:
        sources = _kismet_sources_from_conf()
    radios = _classify_kismet_radios(sources)
    out["wifi"] = radios["wifi"]
    out["bluetooth"] = radios["bluetooth"]
    out["sources"] = radios["sources"]
    return out


def _active_map_label() -> str | None:
    """Human label for the PBF Valhalla is building (from active.json)."""
    try:
        from paths import DATA

        meta_path = DATA / "valhalla" / "active.json"
        if not meta_path.is_file():
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        name = (meta.get("name") or "").strip()
        mode = (meta.get("mode") or "").strip()
        gid = (meta.get("geofabrik_id") or "").strip()
        if name and gid:
            return f"{name} ({gid})"
        if name:
            return name
        if gid:
            return gid
        if mode:
            return mode
    except Exception:
        return None
    return None


def valhalla_service_status() -> dict:
    """Probe Valhalla HTTP; Docker inspect is optional enrichment only."""
    out = container_status(VALHALLA_CONTAINER)
    try:
        from valhalla_client import valhalla_base_url, valhalla_reachable

        url = valhalla_base_url()
        out["url"] = url
        http_ok = valhalla_reachable()
        out["http_ok"] = http_ok
        out["pbf_ready"] = _active_pbf_ready()
        out["regional_pbf"] = _regional_pbf_ready()
        map_label = _active_map_label()
        out["map_label"] = map_label
        if http_ok:
            out["ok"] = True
            out["running"] = True
            out["found"] = True
            out["status"] = "reachable"
            out["detail"] = (
                f"HTTP OK at {url}" + (f" · map {map_label}" if map_label else "")
            )
        elif not out["pbf_ready"] and out["regional_pbf"]:
            out["ok"] = False
            out["status"] = "waiting for seed"
            out["detail"] = (
                "Regional pack downloaded - open Drive and generate a city; "
                "Valhalla starts automatically"
            )
        elif not out["pbf_ready"]:
            out["ok"] = False
            out["status"] = "waiting for map"
            out["detail"] = (
                "No map yet - spawn in Drive and generate a city; "
                "Valhalla starts when the level is ready"
            )
        elif out.get("found") and out.get("running"):
            out["ok"] = False
            out["status"] = "building tiles"
            which = map_label or "active.osm.pbf"
            out["detail"] = (
                f"Building routing tiles for {which} "
                f"(from leftover/city extract - not from opening Drive). "
                f"Can take several minutes."
            )
        elif out.get("found"):
            out["ok"] = False
            out["status"] = "stopped"
            out["detail"] = (
                f"{VALHALLA_CONTAINER} stopped - Drive / level create will restart it"
            )
        else:
            out["ok"] = False
            out["status"] = "not started"
            out["detail"] = (
                f"Map extract ready - starting {VALHALLA_CONTAINER} "
                f"(Drive spawn -> generate city also starts it)"
            )
    except Exception as exc:
        out["http_ok"] = False
        out["detail"] = str(exc)
    return out


def _gpsd_configured_device() -> str:
    """Best-effort device path from env or /etc/default/gpsd."""
    env_dev = (os.getenv("GPSD_DEVICE") or "").strip()
    if env_dev:
        return env_dev
    try:
        text = Path("/etc/default/gpsd").read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("DEVICES="):
                raw = line.split("=", 1)[1].strip().strip("\"'")
                # first path token
                for part in raw.replace(",", " ").split():
                    if part.startswith("/dev/"):
                        return part
    except OSError:
        pass
    return "/dev/ttyACM0"


def gpsd_status(host: str | None = None, port: int | None = None) -> dict:
    host = host or os.getenv("GPSD_HOST", "127.0.0.1")
    if host in {"host.docker.internal", "docker.for.mac.localhost"}:
        host = "127.0.0.1"
    port = int(port or os.getenv("GPSD_PORT", "2947"))
    device = _gpsd_configured_device()
    # /dev may be invisible inside the API container - Path.exists is a hint only.
    path_present = Path(device).exists()
    usb_nodes = [
        p
        for p in ("/dev/ttyACM0", "/dev/ttyACM1", "/dev/ttyUSB0", "/dev/ttyUSB1")
        if Path(p).exists()
    ]
    result = {
        "ok": False,
        "reachable": False,
        "fix": False,
        "mode": 0,
        "lat": None,
        "lon": None,
        "alt": None,
        "speed": None,
        "satellites": None,
        "host": host,
        "port": port,
        "device": device,
        "device_present": path_present,
        "device_path_visible": path_present,
        "usb_gps_nodes": usb_nodes,
        "detail": None,
    }
    try:
        with socket.create_connection((host, port), timeout=2.0) as sock:
            result["reachable"] = True
            sock.settimeout(2.5)
            sock.sendall(b'?WATCH={"enable":true,"json":true}\n')
            buf = b""
            tpv = None
            sky = None
            gpsd_devices: list[str] = []
            try:
                for _ in range(50):
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            msg = json.loads(line.decode("utf-8", errors="replace"))
                        except json.JSONDecodeError:
                            continue
                        cls = msg.get("class")
                        if cls == "DEVICES":
                            for d in msg.get("devices") or []:
                                path = d.get("path") if isinstance(d, dict) else None
                                if path:
                                    gpsd_devices.append(str(path))
                        elif cls == "DEVICE":
                            path = msg.get("path")
                            if path:
                                gpsd_devices.append(str(path))
                        elif cls == "TPV" and tpv is None:
                            tpv = msg
                        elif cls == "SKY" and sky is None:
                            sky = msg
                    if tpv and (gpsd_devices or sky is not None):
                        break
            except TimeoutError:
                pass
            except socket.timeout:
                pass

            # Prefer gpsd's own device list over container /dev visibility
            if gpsd_devices:
                result["usb_gps_nodes"] = sorted(set(gpsd_devices + usb_nodes))
                result["device_present"] = True
                if device not in gpsd_devices and gpsd_devices:
                    # Keep configured path, but note what gpsd actually opened
                    result["gpsd_device"] = gpsd_devices[0]
            elif tpv is not None:
                # Talking to a receiver (even mode 0/1) ⇒ dongle is not "missing"
                result["device_present"] = True

            if not tpv:
                if not result["device_present"]:
                    result["detail"] = (
                        f"gpsd running - no receiver reported "
                        f"(configured {device}"
                        f"{'' if path_present else '; /dev not visible to API container'})"
                    )
                elif usb_nodes and device not in usb_nodes and device not in gpsd_devices:
                    result["detail"] = (
                        f"gpsd running - {device} missing; saw {', '.join(result['usb_gps_nodes'])} "
                        "(update /etc/default/gpsd DEVICES=...)"
                    )
                else:
                    result["detail"] = (
                        f"gpsd running, receiver present - waiting for satellites "
                        "(go outdoors / wait for warm start)"
                    )
                return result
            mode = int(tpv.get("mode") or 0)
            result["mode"] = mode
            result["fix"] = mode >= 2
            result["ok"] = mode >= 2
            result["lat"] = tpv.get("lat")
            result["lon"] = tpv.get("lon")
            result["alt"] = tpv.get("alt") or tpv.get("altHAE")
            result["speed"] = tpv.get("speed")
            result["time"] = tpv.get("time")
            if sky and isinstance(sky.get("satellites"), list):
                sats = sky["satellites"]
                result["satellites"] = len(sats)
                result["satellites_used"] = sum(1 for s in sats if s.get("used"))
            if mode < 2:
                nsat = result.get("satellites")
                used = result.get("satellites_used")
                sat_bit = (
                    f" · {used}/{nsat} sats used"
                    if nsat is not None and used is not None
                    else ""
                )
                result["detail"] = (
                    f"no fix yet (mode {mode}{sat_bit}) - receiver OK, waiting for sky"
                )
            return result
    except OSError as exc:
        result["detail"] = f"{exc} (gpsd host {host}:{port}, device {device})"
        return result


def database_status(user_id: int | None = None) -> dict:
    cfg = db_kwargs()
    out = {
        "ok": False,
        "host": cfg["host"],
        "port": cfg["port"],
        "dbname": cfg["dbname"],
        "user": cfg["user"],
        "size_bytes": None,
        "size_human": None,
        "postgis": None,
        "samples": None,
        "networks": None,
        "networks_wifi": None,
        "networks_bt": None,
        "networks_ble": None,
        "detail": None,
    }
    try:
        conn = connect()
        with conn.cursor() as cur:
            cur.execute("SELECT pg_database_size(current_database())")
            size = cur.fetchone()[0]
            cur.execute("SELECT PostGIS_Version()")
            postgis = cur.fetchone()[0]
            if user_id is not None:
                cur.execute(
                    "SELECT COUNT(*) FROM signal_samples WHERE user_id = %s", (user_id,)
                )
                samples = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM networks WHERE user_id = %s", (user_id,))
                networks = cur.fetchone()[0]
                cur.execute(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE upper(network_type) = 'WIFI') AS wifi,
                        COUNT(*) FILTER (WHERE upper(network_type) = 'BT') AS bt,
                        COUNT(*) FILTER (WHERE upper(network_type) = 'BLE') AS ble
                    FROM networks WHERE user_id = %s
                    """,
                    (user_id,),
                )
                wifi, bt, ble = cur.fetchone()
                cur.execute(
                    """
                    SELECT
                        MIN(seen_at), MAX(seen_at),
                        COUNT(*) FILTER (WHERE source_format = 'kismet'),
                        COUNT(*) FILTER (WHERE source_format = 'wigle')
                    FROM signal_samples WHERE user_id = %s
                    """,
                    (user_id,),
                )
            else:
                cur.execute("SELECT COUNT(*) FROM signal_samples")
                samples = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM networks")
                networks = cur.fetchone()[0]
                cur.execute(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE upper(network_type) = 'WIFI') AS wifi,
                        COUNT(*) FILTER (WHERE upper(network_type) = 'BT') AS bt,
                        COUNT(*) FILTER (WHERE upper(network_type) = 'BLE') AS ble
                    FROM networks
                    """
                )
                wifi, bt, ble = cur.fetchone()
                cur.execute(
                    """
                    SELECT
                        MIN(seen_at), MAX(seen_at),
                        COUNT(*) FILTER (WHERE source_format = 'kismet'),
                        COUNT(*) FILTER (WHERE source_format = 'wigle')
                    FROM signal_samples
                    """
                )
            first_seen, last_seen, from_kismet, from_wigle = cur.fetchone()
        conn.close()
        out.update(
            {
                "ok": True,
                "size_bytes": size,
                "size_human": _bytes_human(size),
                "postgis": postgis,
                "samples": samples,
                "networks": networks,
                "networks_wifi": wifi,
                "networks_bt": bt,
                "networks_ble": ble,
                "first_seen": first_seen.isoformat() if first_seen else None,
                "last_seen": last_seen.isoformat() if last_seen else None,
                "samples_kismet": from_kismet,
                "samples_wigle": from_wigle,
            }
        )
        return out
    except Exception as exc:
        out["detail"] = str(exc)
        return out


def _kismet_log_dir() -> Path:
    env = (os.getenv("KISMET_LOG_DIR") or "").strip()
    if env:
        return Path(env)
    return ROOT / "data" / "kismet_logs"


def _count_files(path: Path) -> int:
    if not path.exists():
        return 0
    n = 0
    for _root, _dirs, files in os.walk(path):
        n += len(files)
    return n


def storage_status(user_id: int | None = None) -> dict:
    """
    Upload queue = manual .kismet / WiGLE drops under data/users/<id>/incoming.
    Live Kismet capture writes to KISMET_LOG_DIR — that is what car setups fill.
    Showing 0 B in the upload queue is normal when you only use live ingest.
    """
    incoming = (
        ROOT / "data" / "users" / str(user_id) / "incoming" if user_id is not None else INCOMING
    )
    uploads_bytes = dir_size_bytes(incoming)
    uploads_files = _count_files(incoming)

    kismet_dir = _kismet_log_dir()
    kismet_bytes = dir_size_bytes(kismet_dir)
    kismet_files = _count_files(kismet_dir)

    disk = shutil.disk_usage(ROOT)
    map_packs: dict = {}
    try:
        from pbf_cache import cache_stats

        map_packs = cache_stats()
    except Exception:
        map_packs = {
            "map_packs_count": 0,
            "map_packs_bytes": 0,
            "map_packs_human": "0 B",
            "map_packs_retention_days": 7,
        }
    return {
        # Legacy keys kept for older UIs
        "raw_incoming_bytes": uploads_bytes,
        "raw_incoming_human": _bytes_human(uploads_bytes),
        "raw_incoming_files": uploads_files,
        "uploads_bytes": uploads_bytes,
        "uploads_human": _bytes_human(uploads_bytes),
        "uploads_files": uploads_files,
        "kismet_logs_bytes": kismet_bytes,
        "kismet_logs_human": _bytes_human(kismet_bytes),
        "kismet_logs_files": kismet_files,
        **map_packs,
        "disk_total_bytes": disk.total,
        "disk_used_bytes": disk.used,
        "disk_free_bytes": disk.free,
        "disk_total_human": _bytes_human(disk.total),
        "disk_used_human": _bytes_human(disk.used),
        "disk_free_human": _bytes_human(disk.free),
        "disk_used_pct": round(100.0 * disk.used / disk.total, 1) if disk.total else None,
    }


def _attach_state(payload: dict, *, expected: bool, state: str) -> dict:
    out = dict(payload)
    out["expected"] = expected
    out["state"] = state
    return out


def _read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return default


def _cpu_times_linux() -> tuple[float, float] | None:
    """Return (idle, total) jiffies from /proc/stat."""
    try:
        line = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0]
    except OSError:
        return None
    parts = line.split()
    if not parts or parts[0] != "cpu" or len(parts) < 5:
        return None
    nums = [float(x) for x in parts[1:]]
    idle = nums[3] + (nums[4] if len(nums) > 4 else 0.0)  # idle + iowait
    total = sum(nums)
    return idle, total


def _cpu_percent() -> float | None:
    """CPU busy % since last Status poll (Linux /proc/stat)."""
    global _cpu_sample
    now = time.monotonic()
    if os.name == "nt":
        return _cpu_percent_windows()
    cur = _cpu_times_linux()
    if not cur:
        return None
    idle, total = cur
    prev = _cpu_sample
    if not prev:
        # First hit: brief sample so the first Status paint isn't empty
        time.sleep(0.08)
        cur2 = _cpu_times_linux()
        if not cur2:
            _cpu_sample = (idle, total, now)
            return None
        idle2, total2 = cur2
        _cpu_sample = (idle2, total2, time.monotonic())
        d_total = total2 - total
        if d_total <= 0:
            return None
        d_idle = idle2 - idle
        return round(max(0.0, min(100.0, 100.0 * (1.0 - d_idle / d_total))), 1)
    _cpu_sample = (idle, total, now)
    d_idle = idle - prev[0]
    d_total = total - prev[1]
    if d_total <= 0:
        return None
    busy = max(0.0, min(100.0, 100.0 * (1.0 - d_idle / d_total)))
    return round(busy, 1)


def _cpu_percent_windows() -> float | None:
    """Rough CPU % via GetSystemTimes (delta since last call)."""
    global _cpu_sample
    try:
        import ctypes
        from ctypes import wintypes

        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

        idle = FILETIME()
        kernel = FILETIME()
        user = FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        ):
            return None

        def _q(ft: FILETIME) -> int:
            return (int(ft.dwHighDateTime) << 32) | int(ft.dwLowDateTime)

        idle_t = float(_q(idle))
        total_t = float(_q(kernel) + _q(user))
        now = time.monotonic()
        prev = _cpu_sample
        if not prev:
            time.sleep(0.08)
            idle2 = FILETIME()
            kernel2 = FILETIME()
            user2 = FILETIME()
            if not ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle2), ctypes.byref(kernel2), ctypes.byref(user2)
            ):
                _cpu_sample = (idle_t, total_t, now)
                return None
            idle_b = float(_q(idle2))
            total_b = float(_q(kernel2) + _q(user2))
            _cpu_sample = (idle_b, total_b, time.monotonic())
            d_total = total_b - total_t
            if d_total <= 0:
                return None
            d_idle = idle_b - idle_t
            return round(max(0.0, min(100.0, 100.0 * (1.0 - d_idle / d_total))), 1)
        _cpu_sample = (idle_t, total_t, now)
        d_idle = idle_t - prev[0]
        d_total = total_t - prev[1]
        if d_total <= 0:
            return None
        # kernel includes idle on Windows
        busy = max(0.0, min(100.0, 100.0 * (1.0 - d_idle / d_total)))
        return round(busy, 1)
    except Exception:
        return None


def _cpu_info() -> dict:
    model = platform.processor() or None
    cores_phys = os.cpu_count()
    threads = os.cpu_count()
    freq_mhz = None
    if Path("/proc/cpuinfo").exists():
        text = _read_text(Path("/proc/cpuinfo"))
        for line in text.splitlines():
            if line.lower().startswith("model name") and ":" in line:
                model = line.split(":", 1)[1].strip() or model
            if line.lower().startswith("cpu mhz") and ":" in line and freq_mhz is None:
                try:
                    freq_mhz = float(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
        # Physical cores from unique core id per package when possible
        phys = set()
        cur_phys = None
        cur_core = None
        for line in text.splitlines():
            if line.startswith("physical id"):
                cur_phys = line.split(":", 1)[1].strip()
            elif line.startswith("core id"):
                cur_core = line.split(":", 1)[1].strip()
            elif not line.strip():
                if cur_phys is not None and cur_core is not None:
                    phys.add((cur_phys, cur_core))
                cur_phys = cur_core = None
        if phys:
            cores_phys = len(phys)
        threads = text.count("processor\t") or text.count("processor ")
        if not threads:
            threads = os.cpu_count()
    elif os.name == "nt":
        try:
            out = subprocess.check_output(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-CimInstance Win32_Processor | Select-Object -First 1 "
                    "Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed) | "
                    "ConvertTo-Json -Compress",
                ],
                timeout=4,
                stderr=subprocess.DEVNULL,
            )
            data = json.loads(out.decode("utf-8", errors="replace"))
            if isinstance(data, list):
                data = data[0] if data else {}
            model = data.get("Name") or model
            if data.get("NumberOfCores"):
                cores_phys = int(data["NumberOfCores"])
            if data.get("NumberOfLogicalProcessors"):
                threads = int(data["NumberOfLogicalProcessors"])
            if data.get("MaxClockSpeed"):
                freq_mhz = float(data["MaxClockSpeed"])
        except Exception:
            pass
    ghz = round(freq_mhz / 1000.0, 2) if freq_mhz else None
    return {
        "model": model,
        "cores": cores_phys,
        "threads": threads,
        "freq_mhz": round(freq_mhz, 0) if freq_mhz else None,
        "freq_ghz": ghz,
        "percent": _cpu_percent(),
    }


def _mem_info() -> dict:
    total = used = avail = None
    if Path("/proc/meminfo").exists():
        kv = {}
        for line in _read_text(Path("/proc/meminfo")).splitlines():
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            m = re.search(r"(\d+)", v)
            if m:
                kv[k.strip()] = int(m.group(1)) * 1024  # kB → bytes
        total = kv.get("MemTotal")
        avail = kv.get("MemAvailable") or kv.get("MemFree")
        if total is not None and avail is not None:
            used = total - avail
    elif os.name == "nt":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                total = int(stat.ullTotalPhys)
                avail = int(stat.ullAvailPhys)
                used = total - avail
        except Exception:
            pass
    pct = round(100.0 * used / total, 1) if total and used is not None else None
    return {
        "total_bytes": total,
        "used_bytes": used,
        "available_bytes": avail,
        "total_human": _bytes_human(total),
        "used_human": _bytes_human(used),
        "available_human": _bytes_human(avail),
        "percent": pct,
    }


def _temp_celsius() -> float | None:
    thermal = Path("/sys/class/thermal")
    if thermal.exists():
        vals = []
        for zone in sorted(thermal.glob("thermal_zone*")):
            raw = _read_text(zone / "temp").strip()
            try:
                # millidegrees C
                vals.append(int(raw) / 1000.0)
            except ValueError:
                continue
        if vals:
            return round(max(vals), 1)
    # hwmon (often CPU package)
    hwmon = Path("/sys/class/hwmon")
    if hwmon.exists():
        vals = []
        for node in hwmon.glob("hwmon*/temp*_input"):
            raw = _read_text(node).strip()
            try:
                vals.append(int(raw) / 1000.0)
            except ValueError:
                continue
        if vals:
            return round(max(vals), 1)
    return None


def _lan_ipv4() -> str | None:
    """Best-effort primary LAN IPv4 (skip loopback / link-local)."""
    candidates: list[str] = []
    try:
        import psutil  # optional

        for _name, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                if getattr(a, "family", None) != socket.AF_INET:
                    continue
                ip = a.address
                if not ip or ip.startswith("127.") or ip.startswith("169.254."):
                    continue
                candidates.append(ip)
    except Exception:
        pass
    if not candidates:
        try:
            hostname = socket.gethostname()
            for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
                ip = info[4][0]
                if ip and not ip.startswith("127.") and not ip.startswith("169.254."):
                    candidates.append(ip)
        except OSError:
            pass
    if not candidates:
        # UDP trick: no packets sent
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            if ip and not ip.startswith("127."):
                return ip
        except OSError:
            pass
        return None
    # Prefer RFC1918
    for ip in candidates:
        if (
            ip.startswith("10.")
            or ip.startswith("192.168.")
            or re.match(r"^172\.(1[6-9]|2\d|3[0-1])\.", ip)
        ):
            return ip
    return candidates[0]


def _wifi_ssid() -> str | None:
    if os.name != "nt":
        for cmd in (
            ["iwgetid", "-r"],
            ["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"],
        ):
            if not shutil.which(cmd[0]):
                continue
            try:
                out = subprocess.check_output(
                    cmd, timeout=3, stderr=subprocess.DEVNULL
                ).decode("utf-8", errors="replace")
            except Exception:
                continue
            if cmd[0] == "iwgetid":
                ssid = out.strip()
                return ssid or None
            for line in out.splitlines():
                if line.startswith("yes:"):
                    return line.split(":", 1)[1].strip() or None
        return None
    try:
        out = subprocess.check_output(
            ["netsh", "wlan", "show", "interfaces"],
            timeout=4,
            stderr=subprocess.DEVNULL,
        ).decode("utf-8", errors="replace")
    except Exception:
        return None
    for line in out.splitlines():
        if "SSID" in line and "BSSID" not in line and ":" in line:
            ssid = line.split(":", 1)[1].strip()
            if ssid:
                return ssid
    return None


def host_machine_status() -> dict:
    """CPU / RAM / disk / temp / LAN / Wi‑Fi for the Status page."""
    cpu = _cpu_info()
    mem = _mem_info()
    disk = shutil.disk_usage(ROOT)
    disk_pct = round(100.0 * disk.used / disk.total, 1) if disk.total else None
    temp = _temp_celsius()
    return {
        "hostname": platform.node() or None,
        "os": f"{platform.system()} {platform.release()}".strip(),
        "cpu": cpu,
        "memory": mem,
        "disk": {
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
            "total_human": _bytes_human(disk.total),
            "used_human": _bytes_human(disk.used),
            "free_human": _bytes_human(disk.free),
            "percent": disk_pct,
        },
        "temperature_c": temp,
        "lan_ip": _lan_ipv4(),
        "wifi_ssid": _wifi_ssid(),
    }


def _state_gps(gps: dict, expected: bool) -> str:
    if not expected:
        return "na"
    if gps.get("fix"):
        return "ok"
    if gps.get("reachable"):
        return "warn"
    return "down"


def _state_container(info: dict, expected: bool) -> str:
    if not expected:
        return "na"
    if info.get("running"):
        return "ok"
    if info.get("found"):
        return "warn"
    return "down"


def _state_db(db: dict, expected: bool) -> str:
    if not expected:
        return "na"
    return "ok" if db.get("ok") else "down"


def collect_system_status(user_id: int | None = None) -> dict:
    mode = deployment_mode()
    expected = deployment_expected(mode)
    db = database_status(user_id=user_id)
    kismet = kismet_service_status()
    # PostGIS: DB probe is authoritative; docker inspect is optional
    postgis_container = container_status(POSTGIS_CONTAINER)
    if db.get("ok"):
        postgis_container["ok"] = True
        postgis_container["running"] = True
        postgis_container["found"] = True
        postgis_container["status"] = postgis_container.get("status") or "db ok"
        if not postgis_container.get("detail") and not postgis_container.get("docker_cli"):
            postgis_container["detail"] = "PostgreSQL/PostGIS reachable (no Docker CLI in API)"
    valhalla = valhalla_service_status()
    gps = gpsd_status()
    storage = storage_status(user_id=user_id)
    try:
        host = host_machine_status()
    except Exception as exc:
        host = {"ok": False, "detail": str(exc)}

    gps = _attach_state(gps, expected=expected["gps"], state=_state_gps(gps, expected["gps"]))

    def _state_kismet(info: dict, exp: bool) -> str:
        if not exp:
            return "na"
        if info.get("http_ok") or info.get("running"):
            return "ok"
        if info.get("found"):
            return "warn"
        return "down"

    kismet = _attach_state(
        kismet, expected=expected["kismet"], state=_state_kismet(kismet, expected["kismet"])
    )

    def _state_valhalla(info: dict, exp: bool) -> str:
        if not exp:
            return "na"
        if info.get("http_ok") or info.get("running"):
            return "ok"
        if info.get("pbf_ready") is False:
            return "warn"  # expected until first level prepare
        if info.get("found"):
            return "warn"
        return "down"

    valhalla = _attach_state(
        valhalla,
        expected=expected["valhalla"],
        state=_state_valhalla(valhalla, expected["valhalla"]),
    )
    postgis_container = _attach_state(
        postgis_container,
        expected=expected["postgis"],
        state=_state_db(db, expected["postgis"])
        if db.get("ok")
        else _state_container(postgis_container, expected["postgis"]),
    )
    db = _attach_state(db, expected=expected["database"], state=_state_db(db, expected["database"]))
    storage = _attach_state(storage, expected=expected["storage"], state="ok")

    if not expected["gps"]:
        gps["detail"] = gps.get("detail") or "Not used in database mode"
    if not expected["kismet"]:
        kismet["detail"] = kismet.get("detail") or "Not used in database mode"
    if not expected["valhalla"]:
        valhalla["detail"] = valhalla.get("detail") or "Not used in database mode"

    return {
        "ok": bool(db.get("ok")),
        "deployment": {"mode": mode, "expected": expected},
        "gps": gps,
        "kismet": kismet,
        "valhalla": valhalla,
        "postgis_container": postgis_container,
        "database": db,
        "storage": storage,
        "host": host,
    }
