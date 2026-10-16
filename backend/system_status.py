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

KISMET_NAMES = ("wardrivrr_kismet", "tesla_kismet", "kismet")
POSTGIS_NAMES = ("wardrivrr_postgis", "tesla_postgis")
VALHALLA_NAMES = ("wardrivrr_valhalla", "tesla_valhalla", "valhalla")


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


def container_status(names: tuple[str, ...]) -> dict:
    """Optional Docker enrichment. API image has no docker CLI — callers must use HTTP probes."""
    if not docker_available():
        return {
            "ok": False,
            "running": False,
            "found": False,
            "name": None,
            "status": "docker unavailable",
            "detail": None,  # not an error by itself inside the API container
            "docker_cli": False,
        }
    for name in names:
        info = _docker_inspect(name)
        if not info:
            continue
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
        "name": None,
        "status": "not found",
        "detail": f"No container matching {', '.join(names)}",
        "docker_cli": True,
    }


def _http_ok(url: str, timeout_s: float = 2.0) -> tuple[bool, str | None]:
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return 200 <= resp.status < 300, f"HTTP {resp.status}"
    except Exception as exc:
        return False, str(exc)


def _active_pbf_ready() -> bool:
    try:
        from paths import DATA

        pbf = DATA / "valhalla" / "active.osm.pbf"
        return pbf.is_file() and pbf.stat().st_size >= 1000
    except Exception:
        return False


def kismet_service_status() -> dict:
    """Host or Docker Kismet — probe HTTP, optionally enrich with docker inspect."""
    base = (os.getenv("KISMET_URL") or "http://127.0.0.1:2501").rstrip("/")
    url = f"{base}/system/status.json"
    ok, detail = _http_ok(url)
    out = container_status(KISMET_NAMES)
    out["url"] = base
    out["http_ok"] = ok
    if ok:
        out["ok"] = True
        out["running"] = True
        out["found"] = True
        out["status"] = "reachable"
        out["detail"] = detail or f"HTTP OK at {base}"
    elif not out.get("detail"):
        out["detail"] = (
            f"Kismet not reachable at {base} — install host packages "
            "(car_setup) or start wardrivrr-kismet.service"
        )
    return out


def valhalla_service_status() -> dict:
    """Probe Valhalla HTTP; do not require Docker CLI inside the API container."""
    out = container_status(VALHALLA_NAMES)
    try:
        from valhalla_client import valhalla_base_url, valhalla_reachable

        url = valhalla_base_url()
        out["url"] = url
        http_ok = valhalla_reachable()
        out["http_ok"] = http_ok
        out["pbf_ready"] = _active_pbf_ready()
        if http_ok:
            out["ok"] = True
            out["running"] = True
            out["found"] = True
            out["status"] = "reachable"
            out["detail"] = f"HTTP OK at {url}"
        elif not out["pbf_ready"]:
            out["ok"] = False
            out["status"] = "waiting for map"
            out["detail"] = (
                "No data/valhalla/active.osm.pbf yet — create a level and run prepare; "
                "Valhalla starts after that"
            )
        elif not out.get("detail"):
            out["detail"] = (
                f"Valhalla not reachable at {url} — tiles may still be building "
                "(docker logs -f wardrivrr_valhalla on the host)"
            )
    except Exception as exc:
        out["http_ok"] = False
        out["detail"] = str(exc)
    return out


def gpsd_status(host: str | None = None, port: int | None = None) -> dict:
    host = host or os.getenv("GPSD_HOST", "127.0.0.1")
    port = int(port or os.getenv("GPSD_PORT", "2947"))
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
        "detail": None,
    }
    try:
        with socket.create_connection((host, port), timeout=1.5) as sock:
            sock.settimeout(1.5)
            sock.sendall(b'?WATCH={"enable":true,"json":true}\n')
            buf = b""
            tpv = None
            sky = None
            for _ in range(40):
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
                    if cls == "TPV" and tpv is None:
                        tpv = msg
                    elif cls == "SKY" and sky is None:
                        sky = msg
                if tpv:
                    break
            result["reachable"] = True
            if not tpv:
                result["detail"] = "gpsd reachable, no TPV yet"
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
                result["detail"] = "no fix"
            return result
    except OSError as exc:
        result["detail"] = str(exc)
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
    postgis_container = container_status(POSTGIS_NAMES)
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
