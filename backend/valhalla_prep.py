"""
Prepare Valhalla input under data/valhalla/active.osm.pbf.

Regional Geofabrik packs live in data/pbf/{extract}.osm.pbf (e.g. Arnsberg…).
Valhalla only sees data/valhalla/ (compose bind mount).

Tiles are always scoped to a selected level (city/district):
  - prefer the level's extract.osm.pbf when present, else
  - osmium-clip the regional pack to the level bbox, then build.

Do not feed Valhalla the whole regional pack — that is what made first builds crawl.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from admin_areas import pbf_path_for_extract
from cpu_workers import valhalla_server_threads
from levels import get_level
from paths import DATA, ROOT

PBF_DIR = DATA / "pbf"
VALHALLA_DIR = DATA / "valhalla"
ACTIVE_PBF = VALHALLA_DIR / "active.osm.pbf"
ACTIVE_META = VALHALLA_DIR / "active.json"
# Soft pad so routes can briefly leave the admin edge (metres → degrees ~ at mid-lat)
BBOX_PAD_DEG = 0.02  # ~1.5–2 km


class ValhallaPrepError(RuntimeError):
    pass


def _pad_bbox(bbox: list[float], pad: float = BBOX_PAD_DEG) -> list[float]:
    west, south, east, north = (float(x) for x in bbox)
    return [
        max(-180.0, west - pad),
        max(-90.0, south - pad),
        min(180.0, east + pad),
        min(90.0, north + pad),
    ]


def _meta_matches(level_id: int, bbox: list[float]) -> bool:
    if not ACTIVE_PBF.exists() or ACTIVE_PBF.stat().st_size < 1000:
        return False
    if not ACTIVE_META.exists():
        return False
    try:
        meta = json.loads(ACTIVE_META.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        int(meta.get("level_id") or -1) == int(level_id)
        and meta.get("bbox") == [round(x, 6) for x in bbox]
    )


def _write_meta(
    *,
    source: str,
    level: dict | None = None,
    bbox: list[float] | None = None,
    mode: str = "seed",
) -> None:
    payload: dict[str, Any] = {
        "mode": mode,
        "source_pbf": source,
        "updated_at": time.time(),
    }
    if level:
        payload["level_id"] = level["id"]
        payload["name"] = level.get("name")
        payload["geofabrik_id"] = level.get("geofabrik_id")
    if bbox is not None:
        payload["bbox"] = [round(x, 6) for x in bbox]
    ACTIVE_META.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def list_regional_pbfs() -> list[Path]:
    """Regional packs in data/pbf (any *.osm.pbf / *.pbf), largest first."""
    if not PBF_DIR.is_dir():
        return []
    found: list[Path] = []
    for path in PBF_DIR.iterdir():
        if not path.is_file():
            continue
        name = path.name.lower()
        if name.endswith(".osm.pbf") or name.endswith(".pbf"):
            if path.stat().st_size >= 1000:
                found.append(path)
    found.sort(key=lambda p: p.stat().st_size, reverse=True)
    return found


def pick_regional_pbf(preferred: Path | None = None) -> Path | None:
    if preferred is not None and preferred.is_file() and preferred.stat().st_size >= 1000:
        return preferred
    packs = list_regional_pbfs()
    return packs[0] if packs else None


def active_pbf_ready() -> bool:
    try:
        return ACTIVE_PBF.is_file() and ACTIVE_PBF.stat().st_size >= 1000
    except OSError:
        return False


def _link_or_copy(src: Path, dest: Path) -> str:
    """Prefer hardlink (same FS), else copy. Returns method used."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp.osm.pbf")
    if tmp.exists() or tmp.is_symlink():
        tmp.unlink()
    try:
        os.link(src, tmp)
        method = "hardlink"
    except OSError:
        shutil.copy2(src, tmp)
        method = "copy"
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    tmp.replace(dest)
    return method


def wipe_valhalla_tiles() -> None:
    tiles = VALHALLA_DIR / "valhalla_tiles"
    if tiles.exists():
        shutil.rmtree(tiles, ignore_errors=True)
    subprocess.run(
        ["docker", "volume", "rm", "-f", "wardrivrr_valhalla_data"],
        capture_output=True,
        text=True,
        timeout=60,
    )


def seed_active_from_regional(
    src: Path | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """
    Ensure data/valhalla/active.osm.pbf exists by linking/copying a regional pack
    from data/pbf (e.g. Arnsberg….osm.pbf). Does not start Valhalla.
    """
    src = pick_regional_pbf(src)
    if src is None:
        raise ValhallaPrepError(
            "No regional map pack in data/pbf/*.osm.pbf — download a Geofabrik extract first"
        )

    VALHALLA_DIR.mkdir(parents=True, exist_ok=True)
    if ACTIVE_PBF.is_dir():
        shutil.rmtree(ACTIVE_PBF, ignore_errors=True)

    already = (
        not force
        and active_pbf_ready()
        and ACTIVE_PBF.stat().st_size == src.stat().st_size
    )
    if already and ACTIVE_META.exists():
        try:
            meta = json.loads(ACTIVE_META.read_text(encoding="utf-8"))
            if meta.get("source_pbf") == str(src) and meta.get("mode") in (
                "seed",
                "clip",
            ):
                return {
                    "ok": True,
                    "seeded": False,
                    "already_current": True,
                    "source_pbf": str(src),
                    "active_pbf": str(ACTIVE_PBF),
                    "active_bytes": ACTIVE_PBF.stat().st_size,
                }
        except (OSError, json.JSONDecodeError):
            pass

    # If a level clip already matches a different size, only overwrite when forced
    # or when active is missing. First-PBF path uses force=False but active missing.
    if active_pbf_ready() and not force:
        if ACTIVE_META.exists():
            try:
                meta = json.loads(ACTIVE_META.read_text(encoding="utf-8"))
                if meta.get("mode") == "clip":
                    return {
                        "ok": True,
                        "seeded": False,
                        "already_current": True,
                        "detail": "Level clip already active — skip regional seed",
                        "source_pbf": str(src),
                        "active_pbf": str(ACTIVE_PBF),
                        "active_bytes": ACTIVE_PBF.stat().st_size,
                    }
            except (OSError, json.JSONDecodeError):
                pass

    method = _link_or_copy(src, ACTIVE_PBF)
    _write_meta(source=str(src), mode="seed")
    return {
        "ok": True,
        "seeded": True,
        "already_current": False,
        "method": method,
        "source_pbf": str(src),
        "active_pbf": str(ACTIVE_PBF),
        "active_bytes": ACTIVE_PBF.stat().st_size,
    }


def _compose_root() -> Path:
    """
    Checkout path that both this process and the Docker daemon can resolve.

    Prefer HOST_PROJECT (absolute host path, same-path bind-mounted into the API
    container). Fall back to WARDRIVRR_COMPOSE_ROOT, then repo ROOT.
    """
    for key in ("HOST_PROJECT", "WARDRIVRR_COMPOSE_ROOT"):
        raw = (os.getenv(key) or "").strip()
        if not raw:
            continue
        path = Path(raw)
        if (path / "docker-compose.yml").is_file():
            return path
    return ROOT


def _host_data_root() -> Path:
    """Host path for ./data — required when docker run mounts from inside the API container."""
    env = (os.getenv("HOST_DATA_ROOT") or "").strip()
    if env:
        return Path(env)
    # Same-path mount: HOST_PROJECT/data
    host_proj = (os.getenv("HOST_PROJECT") or "").strip()
    if host_proj:
        return Path(host_proj) / "data"
    return DATA


def _compose_available() -> bool:
    """True when `docker compose` works (plugin present — not just the docker binary)."""
    try:
        proc = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _compose_cmd() -> list[str]:
    root = _compose_root()
    # --project-directory forces host-relative volume paths for docker-from-docker
    compose = [
        "docker",
        "compose",
        "--project-directory",
        str(root),
        "-f",
        str(root / "docker-compose.yml"),
    ]
    car = root / "deploy" / "compose.car.yml"
    if car.is_file():
        compose.extend(["-f", str(car)])
    env_file = root / ".env"
    if env_file.is_file():
        compose.extend(["--env-file", str(env_file)])
    return compose


def _valhalla_image() -> str:
    return (
        os.getenv("VALHALLA_IMAGE")
        or "ghcr.io/gis-ops/docker-valhalla/valhalla:latest"
    )


def _start_valhalla_docker_run(*, wipe: bool = False) -> dict[str, Any]:
    """
    Start Valhalla with plain `docker run` (no Compose plugin required).

    The API image ships a static docker CLI; older builds lacked the Compose
    plugin, so this path is the reliable docker-from-docker fallback.
    """
    if not active_pbf_ready():
        raise ValhallaPrepError("active.osm.pbf missing — seed or clip first")
    if not _docker_cli_ok():
        raise ValhallaPrepError(
            "Docker CLI unavailable inside API — mount /var/run/docker.sock"
        )

    host_valhalla = (_host_data_root() / "valhalla").resolve()
    if not host_valhalla.is_dir():
        raise ValhallaPrepError(
            f"Host Valhalla data dir missing: {host_valhalla} "
            f"(set HOST_DATA_ROOT to the host ./data path)"
        )

    steps: list[dict[str, Any]] = []
    for args in (
        ["docker", "stop", "wardrivrr_valhalla"],
        ["docker", "rm", "-f", "wardrivrr_valhalla"],
    ):
        proc = subprocess.run(args, capture_output=True, text=True, timeout=60)
        steps.append({"cmd": args[1:], "code": proc.returncode})

    do_wipe = wipe
    if do_wipe:
        wipe_valhalla_tiles()
        steps.append({"cmd": ["wipe_tiles"], "code": 0})

    image = _valhalla_image()
    pull = subprocess.run(
        ["docker", "pull", image],
        capture_output=True,
        text=True,
        timeout=600,
    )
    steps.append(
        {"cmd": ["pull"], "code": pull.returncode, "err": (pull.stderr or "")[-300:]}
    )

    threads = str(valhalla_server_threads())
    run_cmd = [
        "docker",
        "run",
        "-d",
        "--name",
        "wardrivrr_valhalla",
        "--restart",
        "unless-stopped",
        "-p",
        "8002:8002",
        "-e",
        "use_tiles_ignore_pbf=False",
        "-e",
        "build_elevation=False",
        "-e",
        "build_admins=False",
        "-e",
        "build_time_zones=False",
        "-e",
        "serve_tiles=True",
        "-e",
        f"server_threads={threads}",
        "-v",
        f"{host_valhalla}:/custom_files",
        image,
    ]
    proc = subprocess.run(run_cmd, capture_output=True, text=True, timeout=120)
    steps.append(
        {
            "cmd": ["run", "-d"],
            "code": proc.returncode,
            "err": (proc.stderr or proc.stdout or "")[-400:],
            "server_threads": threads,
            "host_mount": str(host_valhalla),
        }
    )
    if proc.returncode != 0:
        raise ValhallaPrepError(
            f"docker run valhalla failed: {(proc.stderr or proc.stdout or '')[-500:]}"
        )
    return {
        "restarted": True,
        "method": "docker_run",
        "wiped_tiles": do_wipe,
        "server_threads": int(threads),
        "steps": steps,
    }


def _compose_env() -> dict[str, str]:
    """Shell env for compose — scales Valhalla threads to accessible cores."""
    env = {k: str(v) for k, v in os.environ.items() if v is not None}
    threads = str(valhalla_server_threads())
    env["VALHALLA_SERVER_THREADS"] = threads
    root = _compose_root()
    env.setdefault("HOST_PROJECT", str(root))
    env.setdefault("HOST_DATA_ROOT", str(_host_data_root()))
    return env


def _docker_cli_ok() -> bool:
    try:
        proc = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _valhalla_container_running() -> bool:
    try:
        proc = subprocess.run(
            [
                "docker",
                "inspect",
                "-f",
                "{{.State.Running}}",
                "wardrivrr_valhalla",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return proc.returncode == 0 and proc.stdout.strip().lower() == "true"
    except (OSError, subprocess.TimeoutExpired):
        return False


def _start_valhalla_container_only() -> dict[str, Any]:
    """Start an existing Valhalla container without compose recreate."""
    proc = subprocess.run(
        ["docker", "start", "wardrivrr_valhalla"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise ValhallaPrepError(
            f"docker start wardrivrr_valhalla failed: "
            f"{(proc.stderr or proc.stdout or '').strip()[-400:]}"
        )
    return {"restarted": True, "method": "docker_start", "wiped_tiles": False}


def _restart_valhalla(*, wipe: bool | None = None) -> dict[str, Any]:
    """Recreate Valhalla so it rebuilds tiles from data/valhalla/active.osm.pbf."""
    if not active_pbf_ready():
        raise ValhallaPrepError("active.osm.pbf missing — seed or clip first")
    if not _docker_cli_ok():
        raise ValhallaPrepError(
            "Docker CLI unavailable inside API — mount /var/run/docker.sock "
            "and set HOST_PROJECT to the host checkout path"
        )

    do_wipe = os.getenv("VALHALLA_WIPE_ON_LEVEL", "1") != "0" if wipe is None else wipe

    # Prefer compose when the plugin exists; otherwise plain docker run
    # (API static docker CLI historically shipped without Compose).
    if not _compose_available():
        return _start_valhalla_docker_run(wipe=do_wipe)

    compose = _compose_cmd()
    root = _compose_root()
    if not (root / "docker-compose.yml").is_file():
        return _start_valhalla_docker_run(wipe=do_wipe)

    cenv = _compose_env()
    threads = cenv["VALHALLA_SERVER_THREADS"]
    steps: list[dict[str, Any]] = []
    for args in (
        ["stop", "valhalla"],
        ["rm", "-f", "valhalla"],
    ):
        proc = subprocess.run(
            [*compose, *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=120,
            env=cenv,
        )
        steps.append({"cmd": args, "code": proc.returncode})

    if do_wipe:
        wipe_valhalla_tiles()
        steps.append({"cmd": ["wipe_tiles"], "code": 0})

    # Pull first so a wiped image does not burn the up() timeout mid-download.
    pull = subprocess.run(
        [*compose, "pull", "valhalla"],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=600,
        env=cenv,
    )
    steps.append(
        {
            "cmd": ["pull", "valhalla"],
            "code": pull.returncode,
            "err": (pull.stderr or "")[-300:],
        }
    )

    proc = subprocess.run(
        [*compose, "up", "valhalla", "-d", "--pull", "missing"],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=300,
        env=cenv,
    )
    steps.append(
        {
            "cmd": ["up", "-d"],
            "code": proc.returncode,
            "err": (proc.stderr or "")[-400:],
            "server_threads": threads,
            "project_directory": str(root),
        }
    )
    if proc.returncode != 0:
        # Fall back: leftover container start, then plain docker run
        try:
            fallback = _start_valhalla_container_only()
            fallback["steps"] = steps
            fallback["compose_error"] = (proc.stderr or proc.stdout or "")[-400:]
            return fallback
        except ValhallaPrepError:
            try:
                run_fb = _start_valhalla_docker_run(wipe=False)
                run_fb["compose_error"] = (proc.stderr or proc.stdout or "")[-400:]
                run_fb["steps"] = steps + list(run_fb.get("steps") or [])
                return run_fb
            except ValhallaPrepError as exc:
                raise ValhallaPrepError(
                    f"Could not start Valhalla: {proc.stderr or proc.stdout}"
                ) from exc
    return {
        "restarted": True,
        "method": "compose_up",
        "wiped_tiles": do_wipe,
        "server_threads": int(threads),
        "steps": steps,
    }


def ensure_valhalla_up(*, wipe: bool = False) -> dict[str, Any]:
    """
    Make sure Valhalla is running against the current active.osm.pbf.

    - If HTTP already OK → no-op
    - If container running but still building → no-op (caller waits)
    - If PBF ready but container down/missing → start/recreate
    """
    from valhalla_client import valhalla_reachable

    if not active_pbf_ready():
        return {
            "ok": False,
            "running": False,
            "detail": "active.osm.pbf missing",
        }
    if valhalla_reachable(timeout_s=1.5):
        return {"ok": True, "running": True, "already": True, "http_ok": True}
    if _valhalla_container_running() and not wipe:
        return {
            "ok": True,
            "running": True,
            "already": True,
            "http_ok": False,
            "detail": "container up — tiles still building",
        }
    try:
        started = _restart_valhalla(wipe=wipe)
        return {"ok": True, "http_ok": False, **started}
    except ValhallaPrepError as exc:
        # Try plain docker start, then docker run (no Compose) before giving up
        try:
            started = _start_valhalla_container_only()
            return {"ok": True, "http_ok": False, **started}
        except ValhallaPrepError:
            try:
                started = _start_valhalla_docker_run(wipe=False)
                return {"ok": True, "http_ok": False, **started}
            except ValhallaPrepError:
                return {
                    "ok": False,
                    "running": False,
                    "restarted": False,
                    "detail": str(exc),
                }


def ensure_valhalla_after_regional_pbf(
    src: Path | None = None,
    *,
    force_seed: bool = False,
    restart: bool = True,
) -> dict[str, Any]:
    """
    Legacy helper — do not call from pack download / boot.

    Feeding Valhalla a full Regierungsbezirk PBF rebuilds tiles for the entire
    region. Prefer prepare_valhalla_for_level (bbox clip) instead.
    Kept for rare debug/manual use only.
    """
    seed = seed_active_from_regional(src, force=force_seed)
    out: dict[str, Any] = {"ok": True, "seed": seed, "legacy": True}
    if not restart:
        return out
    need_wipe = bool(seed.get("seeded") or force_seed)
    out["valhalla"] = ensure_valhalla_up(wipe=need_wipe)
    if not out["valhalla"].get("ok"):
        out["ok"] = False
    return out


def _clip_with_osmium_docker(src: Path, dest: Path, bbox: list[float]) -> None:
    """osmium extract via Docker (reliable on Windows hosts)."""
    west, south, east, north = bbox
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp.osm.pbf")
    if tmp.exists():
        tmp.unlink()

    # Mount host data dir so the Docker daemon (often on the host) sees real paths
    data_root = _host_data_root().resolve()
    try:
        rel_src = src.resolve().relative_to(DATA.resolve()).as_posix()
        rel_tmp = tmp.resolve().relative_to(DATA.resolve()).as_posix()
    except ValueError as exc:
        raise ValhallaPrepError(f"PBF paths must live under data/: {exc}") from exc

    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{data_root}:/data",
        "iboates/osmium:latest",
        "extract",
        "--strategy=complete_ways",
        f"--bbox={west},{south},{east},{north}",
        "-o",
        f"/data/{rel_tmp}",
        f"/data/{rel_src}",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0 or not tmp.exists() or tmp.stat().st_size < 1000:
        err = (proc.stderr or proc.stdout or "").strip()[-800:]
        raise ValhallaPrepError(f"osmium extract failed: {err or 'no output'}")
    tmp.replace(dest)


def prepare_valhalla_for_level(
    user_id: int,
    level_id: int,
    *,
    restart: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """
    Point Valhalla at this level's map extract and start the container.

    Prefers the level's own extract.osm.pbf (already city-scoped). Falls back to
    osmium-clipping a regional Geofabrik pack to the level bbox.
    Always ensures the Valhalla container is up when restart=True.
    """
    from paths import level_dir

    level = get_level(user_id, level_id)
    if not level:
        raise ValhallaPrepError("Level not found")
    if level.get("status") != "ready":
        raise ValhallaPrepError("Level is not ready")

    bbox = level.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise ValhallaPrepError("Level has no bbox — rebuild the level")
    bbox = [float(x) for x in bbox]
    padded = _pad_bbox(bbox)

    level_extract = level_dir(user_id, level_id) / "extract.osm.pbf"
    gid = level.get("geofabrik_id") or ""
    regional = pbf_path_for_extract(gid)
    if not regional.exists() or regional.stat().st_size < 1000:
        regional = pick_regional_pbf() or regional

    VALHALLA_DIR.mkdir(parents=True, exist_ok=True)
    if ACTIVE_PBF.is_dir():
        shutil.rmtree(ACTIVE_PBF, ignore_errors=True)

    clipped = False
    mode = "clip"
    src: Path
    if level_extract.is_file() and level_extract.stat().st_size >= 1000:
        src = level_extract
        mode = "level_extract"
        # Already city-scoped — no osmium. Refresh when forced or level changed.
        need = force or not _meta_matches(level_id, padded)
        if not need and ACTIVE_META.exists():
            try:
                meta = json.loads(ACTIVE_META.read_text(encoding="utf-8"))
                need = int(meta.get("level_id") or -1) != int(level_id)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                need = True
        if need or not active_pbf_ready():
            _link_or_copy(src, ACTIVE_PBF)
            _write_meta(source=str(src), level=level, bbox=padded, mode=mode)
            clipped = True
    else:
        if not isinstance(regional, Path) or not regional.exists() or regional.stat().st_size < 1000:
            raise ValhallaPrepError(
                f"Map pack PBF missing for level {level_id} "
                f"(no extract.osm.pbf and no regional pack for {gid})"
            )
        src = regional
        if force or not _meta_matches(level_id, padded):
            _clip_with_osmium_docker(src, ACTIVE_PBF, padded)
            _write_meta(source=str(src), level=level, bbox=padded, mode=mode)
            clipped = True

    if not active_pbf_ready():
        raise ValhallaPrepError("Failed to prepare active.osm.pbf for Valhalla")

    out: dict[str, Any] = {
        "ok": True,
        "level_id": level_id,
        "name": level.get("name"),
        "bbox": padded,
        "active_pbf": str(ACTIVE_PBF),
        "active_bytes": ACTIVE_PBF.stat().st_size if ACTIVE_PBF.exists() else 0,
        "source_bytes": src.stat().st_size,
        "source_pbf": str(src),
        "mode": mode,
        "clipped": clipped,
        "already_current": not clipped,
    }

    if restart:
        # Always start Valhalla — previously we skipped when "already current"
        # and left fresh installs with a PBF but no container.
        out["valhalla"] = ensure_valhalla_up(wipe=bool(clipped or force))
        if not out["valhalla"].get("ok"):
            out["ok"] = False
            raise ValhallaPrepError(
                out["valhalla"].get("detail")
                or "Could not start Valhalla after preparing the map extract"
            )
    return out
