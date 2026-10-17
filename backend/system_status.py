from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
from pathlib import Path

from db import connect, db_kwargs

ROOT = Path(__file__).resolve().parents[1]
INCOMING = ROOT / "data" / "incoming"

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
    """Optional Docker enrichment. Prefer HTTP probes — API may lack docker CLI."""
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
            return False, "HTTP 401 — check KISMET_USER / KISMET_PASSWORD match kismet_site.conf"
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
    """Parse `source=iface:name=…:type=…` from kismet_site.conf."""
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
        # Heuristic when type missing: wlx*/wlan* → wifi, hci* → bluetooth
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
    """Host or Docker Kismet — probe HTTP with Basic auth from .env."""
    base = (os.getenv("KISMET_URL") or "http://127.0.0.1:2501").rstrip("/")
    # Prefer localhost when .env still has the old Docker-bridge hostname
    if "host.docker.internal" in base:
        base = "http://127.0.0.1:2501"
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
            f"Kismet not reachable at {base} — is kismet.service running?"
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
                "Regional pack downloaded — open Drive and generate a city; "
                "Valhalla starts automatically"
            )
        elif not out["pbf_ready"]:
            out["ok"] = False
            out["status"] = "waiting for map"
            out["detail"] = (
                "No map yet — spawn in Drive and generate a city; "
                "Valhalla starts when the level is ready"
            )
        elif out.get("found") and out.get("running"):
            out["ok"] = False
            out["status"] = "building tiles"
            which = map_label or "active.osm.pbf"
            out["detail"] = (
                f"Building routing tiles for {which} "
                f"(from leftover/city extract — not from opening Drive). "
                f"Can take several minutes."
            )
        elif out.get("found"):
            out["ok"] = False
            out["status"] = "stopped"
            out["detail"] = (
                f"{VALHALLA_CONTAINER} stopped — Drive / level create will restart it"
            )
        else:
            out["ok"] = False
            out["status"] = "not started"
            out["detail"] = (
                f"Map extract ready — starting {VALHALLA_CONTAINER} "
                f"(Drive spawn → generate city also starts it)"
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
    # /dev may be invisible inside the API container — Path.exists is a hint only.
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
                        f"gpsd running — no receiver reported "
                        f"(configured {device}"
                        f"{'' if path_present else '; /dev not visible to API container'})"
                    )
                elif usb_nodes and device not in usb_nodes and device not in gpsd_devices:
                    result["detail"] = (
                        f"gpsd running — {device} missing; saw {', '.join(result['usb_gps_nodes'])} "
                        "(update /etc/default/gpsd DEVICES=…)"
                    )
                else:
                    result["detail"] = (
                        f"gpsd running, receiver present — waiting for satellites "
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
                    f"no fix yet (mode {mode}{sat_bit}) — receiver OK, waiting for sky"
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


def storage_status(user_id: int | None = None) -> dict:
    incoming = (
        ROOT / "data" / "users" / str(user_id) / "incoming" if user_id is not None else INCOMING
    )
    raw_bytes = dir_size_bytes(incoming)
    file_count = 0
    if incoming.exists():
        for _root, _dirs, files in os.walk(incoming):
            file_count += len(files)
    disk = shutil.disk_usage(ROOT)
    return {
        "raw_incoming_path": str(incoming),
        "raw_incoming_bytes": raw_bytes,
        "raw_incoming_human": _bytes_human(raw_bytes),
        "raw_incoming_files": file_count,
        "disk_total_bytes": disk.total,
        "disk_used_bytes": disk.used,
        "disk_free_bytes": disk.free,
        "disk_total_human": _bytes_human(disk.total),
        "disk_used_human": _bytes_human(disk.used),
        "disk_free_human": _bytes_human(disk.free),
    }


def _attach_state(payload: dict, *, expected: bool, state: str) -> dict:
    out = dict(payload)
    out["expected"] = expected
    out["state"] = state
    return out


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
    }
